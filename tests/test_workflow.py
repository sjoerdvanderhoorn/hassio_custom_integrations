import json
import time
from pathlib import Path
import pytest
from app.agent import Jobs
from app.store import Store
from app.installations import Installations, configuration_values
from app.integrations import IntegrationManager, MARKER


class FakeHA:
    def __init__(self):
        self.configured=[];self.calls=[];self.offline=False;self.flow_type='form';self.mutate_error=False;self.state='on'
    def check(self):
        if self.offline: raise RuntimeError('Core offline')
        return {'connected':True}
    def entries(self, domain): return self.configured
    def entity_states(self, domain, entries=None): return {'entities':[{'entity_id':'light.lamp','state':self.state,'attributes':{}}]}
    def restart_core(self): self.calls.append(('restart',))
    def core(self, method, path, **kwargs):
        self.calls.append((method,path,kwargs.get('json')))
        if method=='DELETE': return None
        if self.mutate_error and method=='POST': raise RuntimeError('connection lost after submission')
        if path.endswith('/flow'):
            if self.flow_type=='external':return {'type':'external','flow_id':'pair','step_id':'auth','url':'https://example.invalid/oauth?token=secret'}
            return {'type':'form','flow_id':'one','step_id':'user','data_schema':[{'name':'host'},{'name':'name'}],'errors':{}}
        if method=='GET': return {'type':'form','flow_id':'one','step_id':'user','data_schema':[{'name':'host'}]}
        self.configured=[{'entry_id':'entry-one','title':'Living room','state':'loaded'}]
        return {'type':'create_entry','flow_id':'one','result':{'entry_id':'entry-one'}}


@pytest.fixture

def setup(tmp_path):
    store=Store(tmp_path/'data');manager=IntegrationManager(tmp_path/'data',tmp_path/'ha');ha=FakeHA()
    manager.write_files('test_lamp',[
        {'path':'__init__.py','content':'async def async_setup_entry(hass, entry):\n    return True\n'},
        {'path':'config_flow.py','content':'# fixture\n'},
        {'path':'manifest.json','content':json.dumps({'domain':'test_lamp','name':'Test Lamp','version':'1.0','documentation':'https://example.com','codeowners':[],'iot_class':'local_polling','config_flow':True})}])
    conv=store.new_conversation()
    return store,manager,ha,Installations(store,manager,ha),conv['id']


def wait_now(service, item):
    item=service.get(item['id']);item['not_before']=0;service.store.put('installations',item['id'],item)
    return item


def test_install_restart_resume_configure_verify(setup):
    store,manager,ha,service,conv=setup
    item=service.prepare('test_lamp',{'host':'192.168.0.50','name':'Living room'},conv)
    item=service.deploy(item['id']);assert item['phase']=='awaiting_restart'
    assert not ha.calls
    item=service.restart(item['id']);assert item['phase']=='waiting_core'
    # Simulate both app and Core restarting before configuration.
    restored=Store(store.path.parent);service=Installations(restored,manager,ha)
    item=wait_now(service,item)
    assert service.advance(item['id'])['phase']=='verifying'
    assert service.advance(item['id'])['phase']=='complete'
    assert ha.calls.count(('restart',))==1
    submits=[call for call in ha.calls if len(call)>1 and call[1].endswith('/one') and call[0]=='POST']
    assert submits[0][2]=={'host':'192.168.0.50','name':'Living room'}
    assert 'user_input' not in submits[0][2]
    assert service.get(item['id'])['values']=={}


def test_existing_entry_prevents_duplicate_config_flow(setup):
    store,manager,ha,service,conv=setup
    item=service.prepare('test_lamp',{},conv);service.deploy(item['id']);service.restart(item['id']);wait_now(service,item)
    ha.configured=[{'entry_id':'existing','state':'loaded','title':'Existing'}]
    assert service.advance(item['id'])['phase']=='complete'
    assert not any(len(call)>1 and '/flow' in call[1] for call in ha.calls)


def test_pairing_is_guided_and_reconciled_without_replay(setup):
    store,manager,ha,service,conv=setup
    ha.flow_type='external'
    item=service.prepare('test_lamp',{},conv);service.deploy(item['id']);service.restart(item['id']);wait_now(service,item)
    assert service.advance(item['id'])['phase']=='needs_input'
    item=service.get(item['id']);assert item['flow_id']=='pair'
    assert 'secret' not in json.dumps(item)
    before=len(ha.calls)
    service.advance(item['id']);assert len(ha.calls)==before
    ha.configured=[{'entry_id':'paired','state':'loaded'}]
    assert service.advance(item['id'])['phase']=='complete'


def test_ambiguous_submission_is_never_retried_on_startup(setup):
    store,manager,ha,service,conv=setup
    item=service.prepare('test_lamp',{'host':'lamp.local'},conv);service.deploy(item['id'])
    item=service.get(item['id']);service.update(item,'submitting','In-flight submission',flow_id='one')
    restored=Store(store.path.parent);service=Installations(restored,manager,ha)
    assert service.get(item['id'])['phase']=='reconciling'
    assert service.advance(item['id'])['phase']=='needs_input'
    assert not ha.calls


def test_ambiguous_restart_not_repeated(setup):
    store,manager,ha,service,conv=setup
    item=service.prepare('test_lamp',{},conv);service.deploy(item['id'])
    item=service.get(item['id']);service.update(item,'restart_requested','Restart in flight')
    service=Installations(Store(store.path.parent),manager,ha)
    service.advance(item['id'])
    assert ha.calls==[]


def test_pending_installation_is_deduplicated(setup):
    store,manager,ha,service,conv=setup
    first=service.prepare('test_lamp',{'host':'one'},conv)
    second=service.prepare('test_lamp',{'host':'two'},conv)
    assert first['id']==second['id']
    assert len(service.list())==1


@pytest.mark.parametrize('values',[{'password':'no'},{'api_key':'no'},{'oauth_token':'no'},{'nested':{'secret':'no'}}])
def test_no_credentials_in_installation_plan(values):
    with pytest.raises(ValueError):configuration_values(values)


def test_offline_core_is_retried_but_expired_plan_needs_input(setup):
    store,manager,ha,service,conv=setup
    item=service.prepare('test_lamp',{},conv);service.deploy(item['id']);service.restart(item['id']);wait_now(service,item)
    ha.offline=True
    assert service.advance(item['id'])['phase']=='waiting_core'
    item=service.get(item['id']);item['deadline']=time.time()-1;store.put('installations',item['id'],item)
    assert service.advance(item['id'])['phase']=='needs_input'
    assert len(ha.calls)==1


def test_no_success_for_unavailable_entities(setup):
    store,manager,ha,service,conv=setup
    item=service.prepare('test_lamp',{},conv);service.deploy(item['id']);service.restart(item['id']);wait_now(service,item)
    ha.configured=[{'entry_id':'one','state':'loaded'}];ha.state='unavailable'
    assert service.advance(item['id'])['phase']=='verifying'


def test_job_steps_survive_restart_without_resuming_actions(tmp_path):
    store=Store(tmp_path);conv=store.new_conversation();store.add_message(conv['id'],'user','Build a lamp')
    jobs=Jobs(store);ident=jobs.new(conv['id'])
    jobs.step(ident,'first','write_files',{'domain':'test_lamp','files':[{'content':'password=private'}]})
    jobs.finish_step(ident,'first',{'ok':True,'result':{'written':['light.py']}})
    jobs.step(ident,'second','test_light_or_switch',{'domain':'test_lamp','entity_id':'light.lamp'})
    restarted=Jobs(Store(tmp_path));job=restarted.get(ident)
    assert job['status']=='interrupted'
    assert [step['status'] for step in job['steps']]==['done','interrupted']
    assert job['after_message']==1
    assert 'private' not in json.dumps(job)


def test_interrupted_approval_is_not_reusable(tmp_path):
    store=Store(tmp_path);conv=store.new_conversation();jobs=Jobs(store);ident=jobs.new(conv['id'])
    job=jobs.get(ident);job['status']='approval_required';job['approval']={'id':'stale','title':'Restart','details':{},'decision':None};store.put('jobs',ident,job)
    restarted=Jobs(Store(tmp_path))
    assert restarted.get(ident)['status']=='interrupted'
    with pytest.raises(ValueError):restarted.decide(ident,'stale','approve')


def test_handoff_releases_only_saved_flow_then_opens_preselected_native_setup(setup):
    store,manager,ha,service,conv=setup
    item=service.prepare('test_lamp',{},conv);service.deploy(item['id'])
    item=service.get(item['id']);service.update(item,'needs_input','Pairing needed',flow_id='saved-one')
    link=service.handoff(item['id'])
    assert link['path']=='/config/integrations/add?domain=test_lamp'
    assert ha.calls==[('DELETE','/config/config_entries/flow/saved-one',None)]
    assert service.get(item['id'])['phase']=='manual_setup'
    service.advance(item['id'])
    assert len(ha.calls)==1


def test_handoff_with_existing_config_opens_integration_without_starting_setup(setup):
    store,manager,ha,service,conv=setup
    item=service.prepare('test_lamp',{},conv);service.deploy(item['id'])
    item=service.get(item['id']);service.update(item,'needs_input','Pairing needed',flow_id='saved-one')
    ha.configured=[{'entry_id':'existing','state':'loaded'}]
    assert service.handoff(item['id'])['path']=='/config/integrations/integration/test_lamp'
    assert ha.calls==[]


def test_tool_call_from_old_session_is_not_replayed(setup):
    from app.agent import AgentBridge
    from types import SimpleNamespace as NS
    store,manager,ha,service,conv=setup
    jobs=Jobs(store);old=jobs.new(conv);jobs.step(old,'call-old','restart_home_assistant',{})
    jobs=Jobs(Store(store.path.parent));new=jobs.new(conv)
    bridge=AgentBridge(store,manager,ha,jobs,{},service)
    events=[]
    sessions=NS(retrieve=lambda sid:NS(required_actions=[NS(type='function_call',call_id='call-old',turn_id='turn',name='restart_home_assistant',arguments={})]),events=NS(create=lambda *args,**kwargs:events.extend(kwargs['events'])))
    bridge._handle_required(NS(beta=NS(agents=NS(sessions=sessions))),'session',new,set())
    assert ha.calls==[]
    assert 'not been replayed' in events[0]['output']


def test_agent_install_tool_queues_one_restart_and_durable_configuration(setup):
    from app.agent import AgentBridge
    store,manager,ha,service,conv=setup
    manager.generate_icon('test_lamp','#03A9F4',[{'type':'ellipse','points':[64,32,192,160],'color':'#FFFFFF'}])
    jobs=Jobs(store);job=jobs.new(conv)
    bridge=AgentBridge(store,manager,ha,jobs,{'auto_deploy':True,'auto_restart':True},service)
    result=bridge.tool('install_integration',{'domain':'test_lamp','values':{'host':'192.168.0.50'}},job)
    assert result['ok'] and result['result']['phase']=='waiting_core'
    assert ha.calls==[('restart',)]
    item=service.get(result['result']['installation_id'])
    assert item['values']=={'host':'192.168.0.50'}
    # Same pending plan returned, no second deployment/restart.
    result2=bridge.tool('install_integration',{'domain':'test_lamp','values':{'host':'192.168.0.50'}},job)
    assert result2['result']['installation_id']==item['id']
    assert ha.calls==[('restart',)]
    status=bridge.tool('installation_status',{'domain':'test_lamp'},job)
    assert status['result'][0]['phase']=='waiting_core'
    assert 'values' not in status['result'][0]


def test_corrupt_state_is_not_silently_overwritten(tmp_path):
    path=tmp_path/'state.json';path.write_text('{invalid')
    with pytest.raises(RuntimeError,match='Restore state.json'):
        Store(tmp_path)
    assert path.read_text()=='{invalid'


def test_installation_keeps_original_message_anchor(setup):
    store,manager,ha,service,conv=setup
    store.add_message(conv,'user','Install this lamp')
    item=service.prepare('test_lamp',{},conv)
    store.add_message(conv,'assistant','Installation queued')
    store.add_message(conv,'user','Now add another feature')
    restored=Store(store.path.parent)
    assert restored.records('installations')[item['id']]['after_message']==1


def test_stop_pauses_continuation_until_explicit_resume(setup):
    store,manager,ha,service,conv=setup
    item=service.prepare('test_lamp',{},conv);service.deploy(item['id']);service.restart(item['id']);wait_now(service,item)
    service.pause_conversation(conv)
    assert service.get(item['id'])['phase']=='paused'
    before=list(ha.calls);service.advance(item['id']);assert ha.calls==before
    duplicate=service.prepare('test_lamp',{},conv)
    assert duplicate['id']==item['id']
    assert service.continue_after_manual_restart(item['id'])['phase']=='waiting_core'


def test_stop_during_config_http_call_prevents_the_next_submission(setup):
    import threading
    store,manager,ha,service,conv=setup
    item=service.prepare('test_lamp',{'host':'lamp.local'},conv)
    service.deploy(item['id']);service.restart(item['id']);wait_now(service,item)
    entered=threading.Event();release=threading.Event();paused=threading.Event();original=ha.core
    def waiting_core(method,path,**kwargs):
        if method=='POST' and path.endswith('/flow'):
            entered.set();release.wait(5)
        return original(method,path,**kwargs)
    ha.core=waiting_core
    worker=threading.Thread(target=lambda:service.advance(item['id']));worker.start()
    assert entered.wait(1)
    pauser=threading.Thread(target=lambda:(service.pause_conversation(conv),paused.set()));pauser.start()
    try:
        assert paused.wait(1), 'Stop must not wait for the ongoing config HTTP call'
    finally:
        release.set();worker.join(2);pauser.join(2)
    assert service.get(item['id'])['phase']=='paused'
    assert not any(len(call)>1 and call[1].endswith('/one') for call in ha.calls)
