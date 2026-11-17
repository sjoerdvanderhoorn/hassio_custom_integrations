import json
from pathlib import Path
from io import BytesIO
import pytest
import httpx
from PIL import Image
from app.ha import HAClient
from app.brand import render_icon,validate_png
from app.integrations import IntegrationManager,IntegrationError,safe_relative
from app.agent import AgentBridge,Jobs
from app.store import Store

SHAPES=[
    {'type':'line','points':[48,92,208,92],'color':'#FFFFFF','width':16},
    {'type':'polygon','points':[176,60,216,92,176,124],'color':'#FFFFFF'},
    {'type':'line','points':[208,164,48,164],'color':'#FFFFFF','width':16},
    {'type':'polygon','points':[80,132,40,164,80,196],'color':'#FFFFFF'},
]


def test_core_log_403_explains_required_role_without_bypassing_auth():
    ha=HAClient('private-token');calls=[]
    def respond(request):calls.append(request);return httpx.Response(403,request=request,text='Forbidden')
    ha.client=httpx.Client(transport=httpx.MockTransport(respond),headers={'Authorization':'Bearer private-token'})
    with pytest.raises(RuntimeError,match='hassio_role: homeassistant') as failure:ha.logs('ai_usd_eur')
    assert 'private-token' not in str(failure.value)
    assert len(calls)==1 and calls[0].url.path=='/core/logs'
    assert calls[0].headers['authorization']=='Bearer private-token'


def test_log_reading_keeps_filtering_and_redaction():
    ha=HAClient('fake')
    content='unrelated\n[custom_components.ai_usd_eur] ERROR password=secret\ntrace line'
    ha.client=httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(200,request=request,text=content)))
    result=ha.logs('ai_usd_eur')
    assert 'ERROR' in result['logs'] and 'trace line' in result['logs']
    assert 'secret' not in result['logs']


def test_generated_icon_is_valid_png_and_part_of_deploy_backup_rollback(tmp_path):
    manager=IntegrationManager(tmp_path/'data',tmp_path/'ha')
    files=[{'path':'__init__.py','content':'# integration\n'}, {'path':'manifest.json','content':json.dumps({'domain':'exchange_rate','name':'Exchange Rate','version':'1','documentation':'https://example.org','codeowners':[],'iot_class':'cloud_polling'})}]
    manager.write_files('exchange_rate',files)
    result=manager.generate_icon('exchange_rate','#007FA3',SHAPES)
    icon=manager.workspace('exchange_rate')/'brand/icon.png'
    first=icon.read_bytes();validate_png(first)
    assert Image.open(BytesIO(first)).size==(256,256)
    assert result['path']=='brand/icon.png' and manager.validate('exchange_rate')['ok']
    assert 'Binary brand image: brand/icon.png' in manager.preview('exchange_rate')
    manager.deploy('exchange_rate')
    manager.generate_icon('exchange_rate','#4040A0',SHAPES)
    second=manager.deploy('exchange_rate')
    assert second['backup']
    manager.rollback('exchange_rate',second['backup'])
    assert (manager.installed_path('exchange_rate')/'brand/icon.png').read_bytes()==first
    assert manager.read_file('exchange_rate','brand/icon.png')['format']=='PNG'
    icon.unlink()
    manager.deploy('exchange_rate')
    assert (manager.installed_path('exchange_rate')/'brand/icon.png').read_bytes()==first


@pytest.mark.parametrize('background,shapes',[
    ('not-a-color',SHAPES),('#000000',[]),
    ('#000000',[{'type':'svg','points':[0,0,20,20],'color':'#FFFFFF'}]),
    ('#000000',[{'type':'ellipse','points':[0,0,999,20],'color':'#FFFFFF'}]),
    ('#000000',[{'type':'line','points':[0,0,float('nan'),20],'color':'#FFFFFF'}]),
    ('#000000',[{'type':'rectangle','points':[0,0,20,20],'color':'#FFFFFF','url':'file:///secrets'}]),
])
def test_icon_design_rejects_invalid_or_executable_inputs(background,shapes):
    with pytest.raises(ValueError):render_icon(background,shapes)


def test_png_paths_are_limited_to_brand_assets():
    assert safe_relative('brand/icon.png').as_posix()=='brand/icon.png'
    with pytest.raises(IntegrationError):safe_relative('anything.png')
    with pytest.raises(IntegrationError):safe_relative('../brand/icon.png')
    with pytest.raises(ValueError):validate_png(b'not-png')


def test_agent_requires_icon_for_new_install_and_can_generate_it(tmp_path):
    store=Store(tmp_path/'data');conv=store.new_conversation();jobs=Jobs(store);job=jobs.new(conv['id'])
    manager=IntegrationManager(tmp_path/'data',tmp_path/'ha')
    bridge=AgentBridge(store,manager,object(),jobs,{'auto_deploy':True})
    result=bridge.tool('deploy_integration',{'domain':'exchange_rate'},job)
    assert not result['ok'] and 'generate_integration_icon' in result['reason']
    icon=bridge.tool('generate_integration_icon',{'domain':'exchange_rate','background':'#007FA3','shapes':SHAPES},job)
    assert icon['ok'] and manager.has_icon('exchange_rate')
    assert store.get_conversation(conv['id'])['domains']==['exchange_rate']
