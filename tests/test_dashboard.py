import json
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.ha import HAClient


@pytest.fixture
def dashboard(tmp_path, monkeypatch):
    monkeypatch.setenv('HA_INGRESS_ONLY', '0')
    app = create_app(tmp_path/'data', tmp_path/'config', {})
    domain = app.state.manager.workspace('test_lamp')
    domain.mkdir()
    (domain/'manifest.json').write_text(json.dumps({'domain':'test_lamp', 'name':'Test <Lamp>'}))
    return TestClient(app), app


def test_details_not_installed_but_configured(dashboard, monkeypatch):
    client, app = dashboard
    entries = [{'entry_id':'one','title':'Living room','state':'loaded'}]
    monkeypatch.setattr(HAClient, 'entries', lambda self, domain: entries)
    monkeypatch.setattr(HAClient, 'entity_states', lambda self, domain, entries=None: {'entities':[{'entity_id':'light.lamp','state':'on'}]})
    data = client.get('/api/integrations/test_lamp').json()
    assert data['name'] == 'Test <Lamp>'
    assert data['installed'] is False and data['configured'] is True
    assert data['entries'][0]['title'] == 'Living room'
    assert data['entities'][0]['state'] == 'on'


def test_outage_is_unknown_not_unconfigured(dashboard, monkeypatch):
    client, app = dashboard
    def fail(*args, **kwargs): raise RuntimeError('password=hidden')
    monkeypatch.setattr(HAClient, 'entries', fail)
    data = client.get('/api/integrations/test_lamp').json()
    assert data['configured'] is None and data['entries'] is None and data['entities'] is None
    assert 'hidden' not in json.dumps(data)


def test_foreign_domains_not_inspected(dashboard, monkeypatch):
    client, app = dashboard
    def forbidden(*args): raise AssertionError('Foreign HA read')
    monkeypatch.setattr(HAClient, 'entries', forbidden)
    assert client.get('/api/integrations/hue').status_code == 404
    assert client.get('/api/integrations/bad.name').status_code == 400


def test_entity_failure_preserves_configuration(dashboard, monkeypatch):
    client, app = dashboard
    monkeypatch.setattr(HAClient, 'entries', lambda self, domain: [{'entry_id':'one', 'title':'Office'}])
    def fail(*args, **kwargs): raise RuntimeError('Registry is offline')
    monkeypatch.setattr(HAClient, 'entity_states', fail)
    data = client.get('/api/integrations/test_lamp').json()
    assert data['configured'] is True
    assert data['entries'][0]['title'] == 'Office'
    assert data['entities'] is None and 'entities' in data['errors']


def test_old_default_title_migrates_without_rewriting_history(tmp_path):
    from app.store import Store
    path = tmp_path/'state.json'
    path.write_text(json.dumps({'conversations':{'old':{'title':'Nieuwe integratie','messages':[{'content':'Bewaar dit bericht'}]}}, 'audit':[]}))
    store = Store(tmp_path)
    assert store.data['conversations']['old']['title'] == 'New integration'
    assert store.data['conversations']['old']['messages'][0]['content'] == 'Bewaar dit bericht'


def test_entity_registry_ownership_and_disabled_states(monkeypatch):
    ha = HAClient('fake')
    monkeypatch.setattr(ha, 'entries', lambda domain: [{'entry_id':'one'}])
    registry = [
        {'entity_id':'light.own','config_entry_id':'one'},
        {'entity_id':'sensor.yaml','platform':'test_lamp'},
        {'entity_id':'light.disabled','config_entry_id':'one','disabled_by':'user'},
        {'entity_id':'light.foreign','config_entry_id':'other','platform':'hue'},
    ]
    monkeypatch.setattr(ha, 'websocket_command', lambda command: registry)
    monkeypatch.setattr(ha, 'core', lambda *args: [{'entity_id':'light.own','state':'unavailable','attributes':{}}])
    data = ha.entity_states('test_lamp')
    entities = {e['entity_id']:e for e in data['entities']}
    assert set(entities) == {'light.own','light.disabled','sensor.yaml'}
    assert entities['light.own']['state'] == 'unavailable'
    assert entities['light.disabled']['state'] is None
    assert entities['light.disabled']['disabled_by'] == 'user'


def test_ingress_protection(dashboard, monkeypatch):
    client, app = dashboard
    monkeypatch.setenv('HA_INGRESS_ONLY','1')
    response = client.get('/api/integrations/test_lamp')
    assert response.status_code == 403
    assert response.json()['error'] == 'Accessible only through Home Assistant Ingress'


def test_installation_values_not_exposed_in_state(dashboard, monkeypatch):
    client,app=dashboard
    conversation=app.state.store.new_conversation()
    app.state.installations.prepare('test_lamp',{'host':'192.168.0.50'},conversation['id'])
    monkeypatch.setattr(HAClient,'check',lambda self:{'connected':True})
    data=client.get('/api/state').json()
    assert 'values' not in data['installations'][0]
    assert data['integrations'][0]['name']=='Test <Lamp>'
    data=client.get('/api/conversations/'+conversation['id']).json()
    assert data['domains']==['test_lamp']
    assert 'values' not in data['installations'][0]


def test_restart_action_requires_confirmation(dashboard):
    client,app=dashboard
    assert client.post('/api/installations/anything/action',json={'action':'restart','confirmed':False}).status_code==400


def test_logo_fallback_and_foreign_logo_access(dashboard):
    client,app=dashboard
    response=client.get('/api/integrations/test_lamp/icon')
    assert response.status_code==200 and response.headers['content-type'].startswith('image/svg+xml')
    assert client.get('/api/integrations/hue/icon').status_code==404
