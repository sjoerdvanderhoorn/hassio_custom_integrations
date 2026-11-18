import pytest
from app.agent import AgentBridge, Jobs
from app.store import Store
from app.ha import redact
from app.integrations import IntegrationManager
from app.action_logging import logger


@pytest.fixture
def action_records(caplog):
    logger.addHandler(caplog.handler)
    try:yield caplog
    finally:logger.removeHandler(caplog.handler)


class HAStub:
    def check(self): return {'connected':True}
    def logs(self, domain, limit=100): return {'logs':'good'}
    def entity_states(self, domain): return {'entities':[]}
    def entries(self, domain): return []
    def restart_core(self): return []


def builder(tmp_path):
    store = Store(tmp_path / 'data')
    manager = IntegrationManager(tmp_path / 'data', tmp_path / 'config')
    jobs = Jobs()
    job = jobs.new(store.new_conversation()['id'])
    bridge = AgentBridge(store, manager, HAStub(), jobs, {'auto_deploy':True, 'auto_restart':False, 'allow_device_actions':False})
    return bridge, job


def test_agent_cannot_access_logs_of_foreign_integration(tmp_path):
    bridge, job = builder(tmp_path)
    result = bridge.tool('read_integration_logs', {'domain':'hue'}, job)
    assert result['ok'] is False


def test_device_test_no_longer_needs_option_but_always_needs_approval(tmp_path, monkeypatch):
    bridge, job = builder(tmp_path)
    bridge.manager.workspace('test_lamp').mkdir()
    approvals=[]
    monkeypatch.setattr(bridge.jobs,'request_approval',lambda *args:approvals.append(args) or False)
    result = bridge.tool('test_light_or_switch', {'domain':'test_lamp', 'entity_id':'light.foo', 'service':'turn_on'}, job)
    assert result['ok'] is False
    assert result['reason']=='Test was not approved'
    assert len(approvals)==1


def test_redact_common_tokens():
    secret = 'Authorization: Bearer abcdefghi\npassword=mysecret\nhttps://host/path?token=hello'
    clean = redact(secret)
    assert 'abcdefghi' not in clean
    assert 'mysecret' not in clean
    assert 'token=hello' not in clean


def test_approval_race(tmp_path):
    bridge, job = builder(tmp_path)
    import threading, time
    result = []
    thread = threading.Thread(target=lambda:result.append(bridge.jobs.request_approval(job, 'Test', {'x':1}, timeout=2)))
    thread.start()
    for _ in range(50):
        approval = bridge.jobs.get(job).get('approval')
        if approval: break
        time.sleep(0.01)
    bridge.jobs.decide(job, approval['id'], 'approve')
    thread.join()
    assert result == [True]


@pytest.mark.parametrize('configured_model,expected_model', [(None,'gpt-6.1-sol'),('gpt-6-astra','gpt-6-astra')])
def test_persistent_agent_session_executes_tool_and_followup(tmp_path, monkeypatch,configured_model,expected_model,action_records):
    """Exercise the full integration-side Agents event protocol, no network required."""
    import sys
    from types import SimpleNamespace as NS

    bridge, job = builder(tmp_path)
    conversation_id = bridge.jobs.get(job)['conversation_id']
    tool_results = []
    created_sessions = []
    action = NS(type='function_call', call_id='call-1', turn_id='turn-1', name='home_assistant_info', arguments={})

    class Stream:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def __iter__(self):
            yield NS(type='agent.session.turn.item.added',item=NS(id='search-one',type='web_search_call',status='completed',query='SECRET_QUERY_DO_NOT_LOG'))
            yield NS(type='agent.session.requires_action')
            yield NS(type='agent.session.turn.output_text.done', item_id='msg1', output_index=0, content_index=0, text='De verbinding werkt.')
            yield NS(type='agent.session.turn.completed', turn=NS(subagent_id=None))

    class Events:
        def stream(self, session_id):
            assert session_id == 'sess-abc'
            return Stream()
        def create(self, session_id, events, **kwargs):
            tool_results.extend(events)

    class Sessions:
        def __init__(self): self.events = Events()
        def create(self, **kwargs):
            created_sessions.append(kwargs)
            return NS(id='sess-abc')
        def retrieve(self, session_id): return NS(required_actions=[action])

    class OpenAI:
        def __init__(self, **kwargs): self.beta=NS(agents=NS(sessions=Sessions()))
        def __enter__(self): return self
        def __exit__(self, *args): pass

    monkeypatch.setitem(sys.modules, 'openai', NS(OpenAI=OpenAI))
    bridge.options['openai_api_key'] = 'sk-mock-only'
    if configured_model:bridge.options['model']=configured_model
    bridge.run(conversation_id, 'Controleer Home Assistant', job)
    assert bridge.jobs.get(job)['status'] == 'done'
    assert bridge.store.get_conversation(conversation_id)['session_id'] == 'sess-abc'
    assert any(e['type']=='agent.session.input.tool_result' and 'connected' in e['output'] for e in tool_results)
    assert bridge.store.get_conversation(conversation_id)['messages'][-1]['content'] == 'De verbinding werkt.'
    # Same session reused; no new session created on the second turn.
    job2 = bridge.jobs.new(conversation_id)
    bridge.run(conversation_id, 'En nu?', job2)
    assert bridge.jobs.get(job2)['status'] == 'done'
    assert len(created_sessions) == 1
    assert created_sessions[0]['agent']['model']==expected_model
    assert 'How to test' in created_sessions[0]['agent']['instructions']
    submitted_messages=[event for event in tool_results if event['type']=='agent.session.input.message']
    assert all('How to test checklist' in event['input'][0]['content'][0]['text'] for event in submitted_messages)
    messages='\n'.join(record.getMessage() for record in action_records.records)
    assert 'Searching web documentation' in messages
    assert 'SECRET_QUERY_DO_NOT_LOG' not in messages
