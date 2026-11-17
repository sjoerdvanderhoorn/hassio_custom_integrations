"""Exercise native adapter and authenticated HTTP bridge with explicit HA test doubles."""
import asyncio,importlib.util,json,sys,threading,types
from pathlib import Path
from unittest.mock import Mock
import pytest
from aiohttp import web

BASE=Path(__file__).resolve().parents[1]/'custom_components/custom_integrations'

@pytest.fixture
def modules(monkeypatch):
    # Load our modules under a test-only package, without pretending Core is installed.
    package=types.ModuleType('ci_test');package.__path__=[str(BASE)]
    monkeypatch.setitem(sys.modules,'ci_test',package)
    fake={'homeassistant':types.ModuleType('homeassistant'),'homeassistant.components':types.ModuleType('homeassistant.components'),
          'homeassistant.components.frontend':types.ModuleType('homeassistant.components.frontend'),
          'homeassistant.components.http':types.ModuleType('homeassistant.components.http'),
          'homeassistant.const':types.ModuleType('homeassistant.const'),
          'homeassistant.config_entries':types.ModuleType('homeassistant.config_entries')}
    fake['homeassistant.components.http'].HomeAssistantView=object
    fake['homeassistant.components.http'].StaticPathConfig=lambda *args:args
    fake['homeassistant.const'].EVENT_HOMEASSISTANT_STOP='stop'
    fake['homeassistant.config_entries'].SOURCE_USER='user'
    for name,module in fake.items():monkeypatch.setitem(sys.modules,name,module)
    native=__import__('ci_test.native',fromlist=['NativeHA'])
    spec=importlib.util.spec_from_file_location('ci_test.setup',BASE/'__init__.py',submodule_search_locations=None);setup=importlib.util.module_from_spec(spec);spec.loader.exec_module(setup)
    yield native,setup
    for name in list(sys.modules):
        if name.startswith('ci_test'):sys.modules.pop(name,None)

@pytest.fixture
def adapter(modules,tmp_path):
    native,_=modules
    loop=asyncio.new_event_loop();thread=threading.Thread(target=loop.run_forever,daemon=True);thread.start()
    from app.integrations import IntegrationManager
    manager=IntegrationManager(tmp_path/'data',tmp_path/'ha');manager.workspace('test_lamp').mkdir()
    entries=[types.SimpleNamespace(entry_id='one',domain='test_lamp',title='Lamp',state=types.SimpleNamespace(value='loaded'),disabled_by=None)]
    calls=[]
    async def remove(ident):calls.append(ident);entries.clear();return {'require_restart':False}
    async def execute(fn,*args):return await asyncio.to_thread(fn,*args)
    hass=types.SimpleNamespace(loop=loop,is_stopping=False,config=types.SimpleNamespace(location_name='Test home'),
        config_entries=types.SimpleNamespace(async_entries=lambda domain:list(entries),async_get_entry=lambda ident:next((e for e in entries if e.entry_id==ident),None),async_remove=remove),
        async_create_task=lambda coro,name:asyncio.create_task(coro,name=name),async_add_executor_job=execute,
        data={'system_log':types.SimpleNamespace(records=types.SimpleNamespace(to_list=lambda:[{'name':'custom_components.test_lamp','message':'password=secret failed'},{'name':'custom_components.foreign','message':'foreign secret'}]))})
    client=native.NativeHA(hass);client.manager=manager
    yield client,calls
    loop.call_soon_threadsafe(loop.stop);thread.join();loop.close()

def test_native_entry_removal_and_owned_scope(adapter):
    client,calls=adapter
    assert client.entries('test_lamp')[0]['title']=='Lamp'
    assert client.core('DELETE','/config/config_entries/entry/one')=={'require_restart':False}
    assert calls==['one']
    with pytest.raises(ValueError):client.entries('foreign_lamp')

def test_native_logs_are_scoped_and_redacted(adapter):
    client,_=adapter;logs=client.logs('test_lamp')
    assert 'secret' not in logs['logs'] and '[REDACTED]' in logs['logs'] and 'foreign' not in logs['logs']
    assert 'buffer' in logs['source']

def test_native_stopped_adapter_refuses_new_actions(adapter):
    client,_=adapter;client.closed=True
    with pytest.raises(RuntimeError,match='stopping'):client.entries('test_lamp')

def test_flow_result_never_exposes_credentials(modules):
    native,_=modules
    result=native.NativeHA.flow_result({'type':'create_entry','data':{'password':'secret'},'result':{'token':'secret'},'context':{'secret':1},'title':'Lamp'})
    assert result=={'type':'create_entry'}
    result=native.NativeHA.flow_result({'type':'form','data_schema':types.SimpleNamespace(schema={'host':str}),'description_placeholders':{'secret':'secret'}})
    assert result['data_schema']==[{'name':'host'}] and 'secret' not in json.dumps(result)

class Content:
    def __init__(self,data=b''):self.data=data
    async def iter_chunked(self,size):yield self.data
class Request(dict):
    def __init__(self,admin=True,data=b'',method='GET'):
        super().__init__(hass_user=types.SimpleNamespace(is_admin=admin) if admin is not None else None)
        self.content=Content(data);self.method=method;self.headers={}

def test_http_bridge_requires_admin_and_loaded_entry(modules):
    _,setup=modules;view=setup.EngineView(types.SimpleNamespace(data={}))
    for admin in [False,None]:
        with pytest.raises(web.HTTPForbidden):asyncio.run(view._handle(Request(admin),'api/state'))
    with pytest.raises(web.HTTPServiceUnavailable):asyncio.run(view._handle(Request(True),'api/state'))

def test_http_bridge_restricts_paths_payload_and_forwards_only_body(modules):
    _,setup=modules;seen=[]
    async def request(method,path,**kwargs):
        seen.append((method,path,kwargs));return types.SimpleNamespace(content=b'{"ok":true}',status_code=200,headers={'content-type':'application/json','set-cookie':'must-not-forward'})
    view=setup.EngineView(types.SimpleNamespace(data={'custom_integrations':{'client':types.SimpleNamespace(request=request)}}))
    with pytest.raises(web.HTTPNotFound):asyncio.run(view._handle(Request(),'../state'))
    with pytest.raises(web.HTTPRequestEntityTooLarge):asyncio.run(view._handle(Request(data=b'x'*2000001),'api/chat'))
    result=asyncio.run(view._handle(Request(data=b'{}',method='POST'),'api/chat'))
    assert result.status==200 and 'set-cookie' not in result.headers
    assert seen[0][0:2]==('POST','/api/chat')
    assert 'Authorization' not in seen[0][2]['headers']

def test_manager_cannot_modify_itself(adapter):
    client,_=adapter
    with pytest.raises(ValueError,match='reserved'):client.manager.workspace('custom_integrations')


def test_frozen_old_store_cannot_overwrite_replacement_runtime(tmp_path):
    from app.store import Store
    old=Store(tmp_path);conv=old.new_conversation();old.closed=True
    replacement=Store(tmp_path);replacement.add_message(conv['id'],'user','New runtime message')
    old.add_message(conv['id'],'assistant','Late old worker result')
    fresh=Store(tmp_path)
    assert [m['content'] for m in fresh.get_conversation(conv['id'])['messages']]==['New runtime message']


def test_core_domains_are_protected_and_not_adopted(adapter):
    client,_=adapter
    client.manager.workspace('builtin_lamp').mkdir()
    client.manager.blocked_domains={'builtin_lamp'}
    with pytest.raises(ValueError,match='built-in'):client.manager.write_files('builtin_lamp',[{'path':'__init__.py','content':''}])
    assert all(item['domain']!='builtin_lamp' for item in client.manager.list_domains())


def test_setup_admin_api_unload_and_reload_lifecycle(modules,tmp_path,monkeypatch):
    _,setup=modules
    import homeassistant.components as components
    components.__path__=[str(tmp_path/'builtin')];(tmp_path/'builtin/builtin_sensor').mkdir(parents=True)
    frontend=sys.modules['homeassistant.components.frontend'];registered=[]
    frontend.add_extra_js_url=lambda *args:registered.append(('add',args[-1]))
    frontend.remove_extra_js_url=lambda *args:registered.append(('remove',args[-1]))
    views=[];static=[]
    async def register(paths):static.extend(paths)
    async def executor(fn,*args):return await asyncio.to_thread(fn,*args)
    async def scenario():
        hass=types.SimpleNamespace(loop=asyncio.get_running_loop(),data={},is_stopping=False,
            config=types.SimpleNamespace(config_dir=str(tmp_path/'config'),location_name='Test',path=lambda *parts:str(tmp_path.joinpath('config',*parts))),
            http=types.SimpleNamespace(async_register_static_paths=register,register_view=views.append),
            bus=types.SimpleNamespace(async_listen_once=lambda *args:lambda:None),async_add_executor_job=executor)
        callbacks=[]
        entry=types.SimpleNamespace(data={'openai_api_key':'not-a-real-key'},options={},entry_id='manager',async_on_unload=callbacks.append,add_update_listener=lambda fn:lambda:None)
        assert await setup.async_setup_entry(hass,entry)
        runtime=hass.data['custom_integrations'];assert runtime['app'].state.manager.blocked_domains=={'builtin_sensor'}
        response=await views[0]._handle(Request(),'api/state')
        assert response.status==200 and json.loads(response.body)['ha']['connected']
        conv=runtime['app'].state.store.new_conversation();job=runtime['app'].state.jobs.new(conv['id'])
        assert await setup.async_unload_entry(hass,entry)
        assert runtime['native'].closed and runtime['app'].state.store.closed
        assert runtime['app'].state.jobs.get(job)['stop_requested']
        assert await setup.async_setup_entry(hass,entry)
        assert len(views)==1 and len(static)==1
        assert hass.data['custom_integrations']['app'].state.jobs.get(job)['status']=='interrupted'
        await setup.async_unload_entry(hass,entry)
    asyncio.run(scenario())
    assert [item[0] for item in registered]==['add','remove','add','remove']


def test_native_config_flow_and_options_keep_key_out_of_forms(modules,monkeypatch):
    import voluptuous as vol
    config_entries=sys.modules['homeassistant.config_entries']
    class Flow:
        def __init_subclass__(cls,**kwargs):super().__init_subclass__()
        async def async_set_unique_id(self,value):self.unique_id=value
        def _abort_if_unique_id_configured(self):pass
        def async_show_form(self,**kwargs):return {'type':'form',**kwargs}
        def async_create_entry(self,**kwargs):return {'type':'create_entry',**kwargs}
    config_entries.ConfigFlow=Flow;config_entries.OptionsFlow=Flow
    core=types.ModuleType('homeassistant.core');core.callback=lambda fn:fn
    helpers=types.ModuleType('homeassistant.helpers');selector=types.ModuleType('homeassistant.helpers.selector')
    class TextSelector:
        def __init__(self,*args):pass
        def __call__(self,value):return str(value)
    selector.TextSelector=TextSelector;selector.TextSelectorConfig=dict;selector.TextSelectorType=types.SimpleNamespace(PASSWORD='password')
    for name,module in [('homeassistant.core',core),('homeassistant.helpers',helpers),('homeassistant.helpers.selector',selector)]:monkeypatch.setitem(sys.modules,name,module)
    module=__import__('ci_test.config_flow',fromlist=['CustomIntegrationsFlow'])
    flow=module.CustomIntegrationsFlow();form=asyncio.run(flow.async_step_user())
    assert form['data_schema']({'openai_api_key':'fake'})['model']=='gpt-6.1-sol'
    entry=asyncio.run(flow.async_step_user({'openai_api_key':'fake','model':'gpt-6.1-sol'}))
    assert entry['type']=='create_entry'
    assert asyncio.run(flow.async_step_user({'openai_api_key':'','model':'m'}))['errors']=={'base':'missing_key'}
    options=module.CustomIntegrationsOptions();options.config_entry=types.SimpleNamespace(data={'openai_api_key':'first-secret'},options={'openai_api_key':'replacement-secret'})
    form=asyncio.run(options.async_step_init())
    assert 'secret' not in str(form['data_schema'])
    saved=asyncio.run(options.async_step_init({'openai_api_key':'','model':'m','auto_deploy':False,'auto_restart':False}))
    assert saved['data']['openai_api_key']=='replacement-secret'
