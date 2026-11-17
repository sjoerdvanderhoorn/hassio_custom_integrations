import threading
from types import SimpleNamespace as NS
import pytest
from fastapi.testclient import TestClient
from app.main import create_app
from app.agent import AgentBridge, Jobs
from app.store import Store
from app.integrations import IntegrationManager


@pytest.fixture
def running(tmp_path,monkeypatch):
    monkeypatch.setenv('HA_INGRESS_ONLY','0')
    app=create_app(tmp_path/'data',tmp_path/'ha',{})
    ready=threading.Event();release=threading.Event();events=[]
    class Events:
        def create(self,session,**kwargs):events.append((session,kwargs))
    remote=NS(beta=NS(agents=NS(sessions=NS(events=Events()))))
    def run(cid,message,job):
        app.state.agent.runtimes[job]={'client':remote,'session':'session-one','steered':False}
        app.state.jobs.ready(job,True);ready.set();release.wait(10)
        app.state.jobs.status(job,'stopped' if app.state.agent.stopped(job) else 'done')
    monkeypatch.setattr(app.state.agent,'run',run)
    client=TestClient(app)
    first=client.post('/api/chat',json={'message':'Build a lamp','submission_id':'initial-key'}).json()
    assert ready.wait(2)
    yield client,app,first,events
    release.set()


def test_steering_uses_current_session_and_is_idempotent(running):
    client,app,first,events=running
    body={'conversation_id':first['conversation_id'],'message':'Use a different host','submission_id':'stable-key'}
    response=client.post('/api/chat',json=body)
    assert response.status_code==200 and response.json()['steered']
    assert client.post('/api/chat',json=body).status_code==200
    assert len(events)==1
    assert events[0][0]=='session-one'
    assert events[0][1]['idempotency_key']=='stable-key'
    assert events[0][1]['events'][0]['type']=='agent.session.input.message'
    conv=client.get('/api/conversations/'+first['conversation_id']).json()
    assert [msg['content'] for msg in conv['messages']]==['Build a lamp','Use a different host']
    assert len(conv['jobs'])==1


def test_different_conversation_cannot_steer_active_agent(running):
    client,app,first,events=running
    assert client.post('/api/chat',json={'message':'Other chat'}).status_code==409
    assert events==[]


def test_retry_of_initial_submission_does_not_start_or_steer_again(running):
    client,app,first,events=running
    retry=client.post('/api/chat',json={'message':'Build a lamp','submission_id':'initial-key'})
    assert retry.status_code==200 and retry.json()['job_id']==first['job_id']
    assert events==[]
    assert client.post('/api/chat',json={'message':'Different message','submission_id':'initial-key'}).status_code==409


def test_failed_cancel_does_not_claim_remote_was_stopped(running,monkeypatch):
    client,app,first,events=running
    def fail(*args,**kwargs):raise RuntimeError('Network offline')
    runtime=app.state.agent.runtimes[first['job_id']]
    monkeypatch.setattr(runtime['client'].beta.agents.sessions.events,'create',fail)
    response=client.post('/api/jobs/'+first['job_id']+'/stop',json={})
    assert response.status_code==502
    assert app.state.jobs.get(first['job_id'])['status']=='stop_unconfirmed'
    assert app.state.jobs.get(first['job_id'])['stop_requested']


def test_stop_sends_remote_cancel_and_blocks_next_tool(running):
    client,app,first,events=running
    response=client.post('/api/jobs/'+first['job_id']+'/stop',json={})
    assert response.status_code==200
    assert events[-1][1]['events']==[{'type':'agent.session.input.cancel'}]
    assert app.state.jobs.get(first['job_id'])['stop_requested']
    assert not app.state.jobs.get(first['job_id'])['can_steer']
    result=app.state.agent.tool('restart_home_assistant',{},first['job_id'])
    assert result['ok'] is False and 'stopped' in result['reason']
    assert client.post('/api/chat',json={'conversation_id':first['conversation_id'],'message':'Continue'}).status_code==409


def test_stop_releases_pending_approval_without_authorizing(tmp_path):
    store=Store(tmp_path);conv=store.new_conversation();jobs=Jobs(store);job=jobs.new(conv['id']);result=[]
    waiting=threading.Event()
    original=jobs._save
    def save(value):
        original(value)
        if value['status']=='approval_required':waiting.set()
    jobs._save=save
    thread=threading.Thread(target=lambda:result.append(jobs.request_approval(job,'Operate light',{},timeout=2)))
    thread.start();assert waiting.wait(1)
    approval=jobs.get(job)['approval']['id'];jobs.request_stop(job);thread.join(2)
    assert result==[False]
    assert jobs.get(job)['status']=='stopping'
    with pytest.raises(ValueError):jobs.decide(job,approval,'approve')


def test_cancellation_event_is_stopped_not_failure(tmp_path,monkeypatch):
    import sys
    store=Store(tmp_path/'data');conv=store.new_conversation();manager=IntegrationManager(tmp_path/'data',tmp_path/'ha');jobs=Jobs(store);job=jobs.new(conv['id'])
    class Stream:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def __iter__(self):yield NS(type='agent.session.turn.cancelled',turn=NS(subagent_id=None))
    sessions=NS(create=lambda **kwargs:NS(id='session'),events=NS(stream=lambda sid:Stream(),create=lambda *args,**kwargs:None))
    class OpenAI:
        def __init__(self,**kwargs):self.beta=NS(agents=NS(sessions=sessions))
        def __enter__(self):return self
        def __exit__(self,*args):pass
    monkeypatch.setitem(sys.modules,'openai',NS(OpenAI=OpenAI))
    bridge=AgentBridge(store,manager,NS(),jobs,{'openai_api_key':'mock-only'})
    bridge.run(conv['id'],'A message',job)
    assert jobs.get(job)['status']=='stopped'
    assert not [event for event in jobs.get(job)['events'] if event['kind']=='error']
    assert not jobs.get(job)['can_steer']


def test_stop_before_start_does_not_start_remote_session(tmp_path):
    store=Store(tmp_path/'data');conv=store.new_conversation();jobs=Jobs(store);job=jobs.new(conv['id'])
    manager=IntegrationManager(tmp_path/'data',tmp_path/'ha');bridge=AgentBridge(store,manager,NS(),jobs,{})
    jobs.request_stop(job);bridge.run(conv['id'],'Do not run',job)
    assert jobs.get(job)['status']=='stopped'
