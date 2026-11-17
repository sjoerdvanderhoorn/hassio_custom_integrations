import json
import logging
from html.parser import HTMLParser
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.ha import HAClient
from app.markdown import render_markdown
from app.agent import Jobs
from app.store import Store
from app.action_logging import logger


@pytest.fixture
def hub(tmp_path,monkeypatch):
    monkeypatch.setenv('HA_INGRESS_ONLY','0')
    monkeypatch.setattr(HAClient,'check',lambda self:{'connected':True})
    app=create_app(tmp_path/'data',tmp_path/'ha',{})
    workspace=app.state.manager.workspace('currency');workspace.mkdir()
    (workspace/'manifest.json').write_text(json.dumps({'domain':'currency','name':'PLN/EUR Exchange Rate'}))
    return TestClient(app),app


def test_navigation_only_lists_named_integrations_and_related_conversations(hub):
    client,app=hub
    linked=app.state.store.new_conversation('currency')
    orphan=app.state.store.new_conversation()
    unnamed=app.state.store.new_conversation('unnamed_draft')
    app.state.manager.workspace('unnamed_draft').mkdir()
    data=client.get('/api/state').json()
    assert [conv['id'] for conv in data['conversations']]==[linked['id']]
    assert [item['domain'] for item in data['integrations']]==['currency']
    assert orphan['id'] not in json.dumps(data['conversations'])
    assert unnamed['id'] not in json.dumps(data['conversations'])


def test_entity_names_prefer_registry_name_and_remove_integration_prefix(hub,monkeypatch):
    client,app=hub
    monkeypatch.setattr(HAClient,'entries',lambda self,domain:[{'entry_id':'one','title':'PLN/EUR Exchange Rate'}])
    monkeypatch.setattr(HAClient,'entity_states',lambda *args,**kwargs:{'entities':[
        {'entity_id':'sensor.rate','state':'4.4','original_name':'EUR to PLN','attributes':{'friendly_name':'PLN/EUR Exchange Rate EUR to PLN'}},
        {'entity_id':'sensor.date','state':'2026-11-17','attributes':{'friendly_name':'PLN/EUR Exchange Rate Publication date'}},
        {'entity_id':'sensor.other','state':'on','name':'Explicit label','attributes':{'friendly_name':'Other prefix'}}]})
    data=client.get('/api/integrations/currency').json()
    assert [entity['display_name'] for entity in data['entities']]==['EUR to PLN','Publication date','Explicit label']


def test_assistant_markdown_is_rendered_without_rewriting_persisted_text(hub):
    client,app=hub
    conv=app.state.store.new_conversation('currency')
    original='## Result\n\n**Ready**\n\n```python\nprint("hello")\n```\n\n| Name | Value |\n| --- | --- |\n| Rate | 4.4 |'
    app.state.store.add_message(conv['id'],'assistant',original)
    message=client.get('/api/conversations/'+conv['id']).json()['messages'][0]
    assert '<h2>Result</h2>' in message['rendered_content']
    assert '<strong>Ready</strong>' in message['rendered_content']
    assert '<pre><code>' in message['rendered_content'] and '<table>' in message['rendered_content']
    assert app.state.store.get_conversation(conv['id'])['messages'][0]['content']==original
    assert 'rendered_content' not in app.state.store.get_conversation(conv['id'])['messages'][0]


@pytest.mark.parametrize('text',[
    '<script>alert(1)</script>', '<img src=x onerror=alert(1)>',
    '[click](javascript:alert(1))','[click](data:text/html;base64,evil)',
    '<a href="javascript:alert(1)" onclick="alert(1)">click</a>',
    '```html\n<img src=x onerror=alert(1)>\n```',
])
def test_markdown_does_not_create_executable_html(text):
    class Inspector(HTMLParser):
        def handle_starttag(self,tag,attrs):
            assert tag not in {'script','iframe','img','object','embed','svg'}
            for key,value in attrs:
                assert not key.startswith('on')
                if key=='href':assert not value.lower().startswith(('javascript:','data:'))
    Inspector().feed(render_markdown(text))


def test_activity_and_log_capability_are_scoped_and_cached(hub,monkeypatch):
    client,app=hub;calls=[]
    monkeypatch.setattr(HAClient,'entity_states',lambda self,domain:{'entities':[{'entity_id':'sensor.rate'}]})
    monkeypatch.setattr(HAClient,'activity',lambda self,domain,entities: calls.append(('activity',domain,entities)) or {'available':True,'events':[],'truncated':False})
    monkeypatch.setattr(HAClient,'logs',lambda self,domain,limit:calls.append(('logs',domain,limit)) or {'logs':''})
    data=client.get('/api/integrations/currency/activity').json()
    assert data['available'] and data['logs_available']
    assert client.get('/api/integrations/currency/activity').json()==data
    assert len(calls)==2 and calls[0][1]=='currency'
    assert client.get('/api/integrations/foreign/activity').status_code==404
    assert client.get('/api/integrations/foreign/logs').status_code==404
    assert len(calls)==2


def test_missing_log_access_hides_capability(hub,monkeypatch):
    client,app=hub
    def unavailable(*args,**kwargs):raise RuntimeError('Not available')
    monkeypatch.setattr(HAClient,'entity_states',unavailable)
    monkeypatch.setattr(HAClient,'logs',unavailable)
    data=client.get('/api/integrations/currency/activity').json()
    assert not data['available'] and not data['logs_available']
    assert client.get('/api/integrations/currency/logs').status_code==503


def test_logbook_never_requests_global_activity_and_filters_foreign_rows(monkeypatch):
    ha=HAClient('fake');commands=[]
    def command(payload):
        commands.append(payload)
        return [{'when':1,'entity_id':'sensor.own','state':'on'},{'when':2,'entity_id':'sensor.foreign','state':'off'}]
    monkeypatch.setattr(ha,'websocket_command',command)
    assert ha.activity('currency',[])['events']==[] and not commands
    result=ha.activity('currency',[{'entity_id':'sensor.own'}])
    assert commands[0]['type']=='logbook/get_events'
    assert commands[0]['entity_ids']==['sensor.own']
    assert [event['entity_id'] for event in result['events']]==['sensor.own']


def test_developer_console_logs_action_labels_without_payloads(tmp_path):
    records=[]
    class Capture(logging.Handler):
        def emit(self,record):records.append(record.getMessage())
    handler=Capture();logger.addHandler(handler)
    try:
        store=Store(tmp_path);conv=store.new_conversation();jobs=Jobs(store);job=jobs.new(conv['id'])
        jobs.step(job,'call','write_files',{'content':'API_SECRET_DO_NOT_LOG','host':'192.168.1.20'})
        jobs.finish_step(job,'call',{'ok':True,'result':{'content':'RESULT_DO_NOT_LOG'}})
        jobs.status(job,'done')
    finally:logger.removeHandler(handler)
    text='\n'.join(records)
    assert 'Action started' in text and 'Updating integration code' in text and 'Action finished' in text
    assert 'API_SECRET_DO_NOT_LOG' not in text and 'RESULT_DO_NOT_LOG' not in text and '192.168.1.20' not in text
