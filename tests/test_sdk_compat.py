"""Use the actual OpenAI SDK with an HTTP mock, not a mocked SDK namespace."""
import json
import httpx
from openai import OpenAI
from app.agent import AgentBridge,Jobs
from app.store import Store
from app.integrations import IntegrationManager

def test_actual_sdk_agents_payload_and_event_stream(tmp_path,monkeypatch):
    calls=[]
    events=[{'type':'agent.session.turn.output_text.done','item_id':'message-one','output_index':0,'content_index':0,'text':'## How to test\n\nCheck the parcel status.'},
            {'type':'agent.session.turn.completed','turn':{'id':'turn-one','subagent_id':None}}]
    def transport(request):
        calls.append(request)
        if request.url.path.endswith('/agents/sessions'):
            return httpx.Response(200,json={'id':'session-one','object':'agent.session','status':'idle'})
        if request.method=='GET' and request.url.path.endswith('/events'):
            body=''.join('data: '+json.dumps(event)+'\n\n' for event in events)+'data: [DONE]\n\n'
            return httpx.Response(200,headers={'content-type':'text/event-stream'},content=body.encode())
        if request.method=='POST' and request.url.path.endswith('/events'):return httpx.Response(204)
        raise AssertionError(str(request.url))
    real=OpenAI(api_key='test-only',http_client=httpx.Client(transport=httpx.MockTransport(transport)))
    import openai
    monkeypatch.setattr(openai,'OpenAI',lambda **kwargs:real)
    store=Store(tmp_path/'data');manager=IntegrationManager(tmp_path/'data',tmp_path/'ha');jobs=Jobs(store)
    conv=store.new_conversation();job=jobs.new(conv['id'])
    bridge=AgentBridge(store,manager,None,jobs,{'openai_api_key':'test-only'})
    bridge.run(conv['id'],'Build a parcel tracker',job)
    assert jobs.get(job)['status']=='done',jobs.get(job)
    payload=json.loads(calls[0].content)
    assert payload['agent']['model']=='gpt-6.1-sol'
    assert payload['environment']['type']=='openai_hosted'
    assert any(tool.get('name')=='uninstall_integration' for tool in payload['agent']['tools'])
    assert all(request.headers.get('OpenAI-Beta')=='agents=v1' for request in calls)
    assert 'How to test' in store.get_conversation(conv['id'])['messages'][-1]['content']
