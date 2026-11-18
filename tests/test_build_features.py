"""Discovery gates, bounded batch reads, snapshots and non-replaying stream recovery."""
import json,sys
from types import SimpleNamespace as NS
import pytest
from app.agent import AgentBridge,Jobs
from app.store import Store
from app.integrations import IntegrationManager

@pytest.fixture
def bridge(tmp_path):
 store=Store(tmp_path/'data');conv=store.new_conversation();jobs=Jobs(store);job=jobs.new(conv['id'])
 mgr=IntegrationManager(tmp_path/'data',tmp_path/'ha');return AgentBridge(store,mgr,NS(),jobs,{'openai_api_key':'test','auto_deploy':True}),conv['id'],job

def files(domain='sample_light',name='Sample Light'):
 return [{'path':'__init__.py','content':'# v1\n'},{'path':'manifest.json','content':json.dumps({'domain':domain,'name':name,'version':'1.0','documentation':'https://example.com','codeowners':[],'iot_class':'local_polling'})}]

def test_discovery_blocks_build_and_cannot_be_erased(bridge):
 b,cid,job=bridge
 assert not b.tool('write_files',{'domain':'sample_light','files':files()},job)['ok']
 result=b.tool('report_integration_discovery',{'summary':'Official documentation matches the device','matches':[{'domain':'hue','name':'Philips Hue','url':'https://www.home-assistant.io/integrations/hue/','reason':'Supports this lamp through its bridge'}]},job)
 assert result['needs_user_choice']
 assert not b.tool('write_files',{'domain':'sample_light','files':files()},job)['ok']
 b.tool('report_integration_discovery',{'summary':'Changed my mind','matches':[]},job)
 assert b.store.records('discoveries')[cid]['matches']
 assert not b.manager.workspace('sample_light').exists()
 b.store.confirm_custom_build(cid)
 assert b.tool('write_files',{'domain':'sample_light','files':files()},job)['ok']
 assert b.store.get_conversation(cid)['messages'][-1]['integration_discovery']['matches'][0]['name']=='Philips Hue'

def test_no_match_and_existing_edit_paths(bridge):
 b,cid,job=bridge
 assert b.tool('report_integration_discovery',{'summary':'Checked current official documentation; no exact match found.','matches':[]},job)['ok']
 assert b.tool('write_files',{'domain':'sample_light','files':files()},job)['ok']
 other=b.store.new_conversation('sample_light');new=b.jobs.new(other['id'])
 assert b.tool('write_files',{'domain':'sample_light','files':[{'path':'__init__.py','content':'# edited'}]},new)['ok']

def test_bulk_reads_boundaries_and_history_restore(bridge):
 b,_,_=bridge;mgr=b.manager
 mgr.write_files('sample_light',files());first=mgr.history.list('sample_light')[0]
 mgr.write_files('sample_light',[{'path':'__init__.py','content':'# v2'}])
 revisions=mgr.history.list('sample_light');assert len(revisions)>=2 and revisions[0]['created']>=first['created']
 assert mgr.history.read('sample_light',first['id'],['__init__.py'])['files'][0]['content']=='# v1\n'
 assert len(mgr.read_files('sample_light',['__init__.py','manifest.json'])['files'])==2
 with pytest.raises(ValueError):mgr.read_files('sample_light',['../secrets.yaml'])
 with pytest.raises(ValueError):mgr.read_files('sample_light',['x']*31)
 restored=mgr.history.restore('sample_light',first['id'])
 assert restored['restored_to']=='staging' and not restored['installed_code_changed']
 assert mgr.read_file('sample_light','__init__.py')['content']=='# v1\n'
 assert not mgr.installed_path('sample_light').exists()
 with pytest.raises(ValueError):mgr.history.restore('sample_light','../outside')

def test_batch_read_size_and_snapshot_deduplication(bridge):
 b,_,_=bridge;mgr=b.manager
 mgr.write_files('sample_light',files()+[{'path':'big.txt','content':'x'*95000}])
 with pytest.raises(ValueError):mgr.read_files('sample_light',['big.txt'])
 before=len(mgr.history.list('sample_light'));mgr.history.save('sample_light','Unchanged');assert len(mgr.history.list('sample_light'))==before

def test_restore_always_requires_approval(bridge,monkeypatch):
 b,_,job=bridge;b.manager.write_files('sample_light',files());rev=b.manager.history.list('sample_light')[0]['id']
 approvals=[];monkeypatch.setattr(b.jobs,'request_approval',lambda *args:approvals.append(args) or False)
 assert not b.tool('restore_revision',{'domain':'sample_light','revision':rev},job)['ok']
 assert approvals

class EmptyStream:
 def __init__(self,events=()):self.events=events
 def __enter__(self):return self
 def __exit__(self,*args):pass
 def __iter__(self):return iter(self.events)

def sdk(monkeypatch,streams):
 class Events:
  def __init__(self):self.opens=0;self.sent=[]
  def stream(self,sid):
   index=self.opens;self.opens+=1;return EmptyStream(streams[min(index,len(streams)-1)])
  def create(self,sid,events,**kwargs):self.sent.extend(events)
 events=Events();sessions=NS(events=events,create=lambda **kwargs:NS(id='session'),retrieve=lambda sid:NS(status='in_progress',required_actions=[]))
 class Client:
  def __init__(self,**kwargs):self.beta=NS(agents=NS(sessions=sessions))
  def __enter__(self):return self
  def __exit__(self,*args):pass
 monkeypatch.setitem(sys.modules,'openai',NS(OpenAI=Client));monkeypatch.setattr('app.agent.time.sleep',lambda seconds:None)
 return events,sessions

def terminal(text='Ready'):
 return [NS(type='agent.session.turn.output_text.done',item_id='answer',output_index=0,content_index=0,text=text),NS(type='agent.session.turn.completed',turn=NS(id='turn1',subagent_id=None))]

def test_stream_reconnects_three_times_without_resending(bridge,monkeypatch):
 b,cid,job=bridge;events,_=sdk(monkeypatch,[[],[],[],terminal()])
 b.run(cid,'Create something',job)
 assert b.jobs.get(job)['status']=='done' and events.opens==4
 assert len([e for e in events.sent if e['type']=='agent.session.input.message'])==1
 assert len([e for e in b.jobs.get(job)['events'] if e['kind']=='retry'])==3

def test_exhausted_retries_persist_and_manual_resume_does_not_resubmit(bridge,monkeypatch):
 b,cid,job=bridge;events,_=sdk(monkeypatch,[[]])
 b.run(cid,'A large request',job);assert b.jobs.get(job)['retryable'] and b.jobs.get(job)['status']=='failed'
 assert 'too big' in b.store.get_conversation(cid)['messages'][-1]['content']
 assert b.store.records('recoveries')[job]['session_id']=='session'
 events2,_=sdk(monkeypatch,[terminal()]);b.jobs.status(job,'working');b.run(cid,'',job,resume=True)
 assert b.jobs.get(job)['status']=='done' and not b.jobs.get(job)['retryable']
 assert not any(e['type']=='agent.session.input.message' for e in events2.sent)

def test_stop_during_retry_prevents_more_streams(bridge,monkeypatch):
 b,cid,job=bridge;events,_=sdk(monkeypatch,[[]])
 monkeypatch.setattr('app.agent.time.sleep',lambda seconds:b.jobs.request_stop(job))
 b.run(cid,'Task',job)
 assert events.opens==1  # stopping interrupts the retry loop before another connection
 assert len([e for e in events.sent if e['type']=='agent.session.input.message'])==1

def test_review_link_is_appended_from_real_manifest(bridge,monkeypatch):
 b,cid,job=bridge;b.manager.write_files('sample_light',files())
 b.jobs.step(job,'write','write_files',{'domain':'sample_light'});b.jobs.finish_step(job,'write',{'ok':True})
 sdk(monkeypatch,[terminal('Created.')]);b.run(cid,'Build',job)
 answer=b.store.get_conversation(cid)['messages'][-1]['content'];assert '[Sample Light](/config/integrations/integration/sample_light)' in answer

def test_completed_turn_can_be_recovered_without_another_message(bridge,monkeypatch):
 b,cid,job=bridge;events,sessions=sdk(monkeypatch,[[NS(type='agent.session.turn.started',turn=NS(id='turn1'))]])
 sessions.retrieve=lambda sid:NS(status='idle')
 sessions.turns=NS(retrieve=lambda *args,**kwargs:NS(id='turn1',status='completed',subagent_id=None),items=NS(list=lambda *args,**kwargs:NS(data=[NS(type='message',role='assistant',id='answer',content=[NS(type='output_text',text='Recovered answer')])])))
 b.run(cid,'Task',job)
 assert b.jobs.get(job)['status']=='done' and events.opens==1
 assert b.store.get_conversation(cid)['messages'][-1]['content']=='Recovered answer'


def test_tool_result_retry_reuses_cached_result_without_rewriting(bridge,monkeypatch):
 b,cid,job=bridge
 b.tool('report_integration_discovery',{'summary':'No suitable integration found','matches':[]},job)
 events,sessions=sdk(monkeypatch,[[NS(type='agent.session.requires_action')],terminal('Created')])
 action=NS(type='function_call',call_id='call-write',turn_id='turn1',name='write_files',arguments={'domain':'sample_light','files':files()})
 sessions.retrieve=lambda sid:NS(status='requires_action',required_actions=[action])
 sent=[];base_create=events.create
 class APIConnectionError(RuntimeError):pass
 def send(sid,events,**kwargs):
  if events[0]['type']=='agent.session.input.tool_result':
   sent.append((events,kwargs))
   if len(sent)==1:raise APIConnectionError('Simulated lost acknowledgement')
  return base_create(sid,events,**kwargs)
 events.create=send
 writes=[];write=b.manager.write_files
 def count(*args):writes.append(args);return write(*args)
 monkeypatch.setattr(b.manager,'write_files',count)
 b.run(cid,'Build a light',job)
 assert b.jobs.get(job)['status']=='done' and len(writes)==1
 assert len(sent)==2 and sent[0]==sent[1]
 assert '[Sample Light](/config/integrations/integration/sample_light)' in b.store.get_conversation(cid)['messages'][-1]['content']


def test_discovery_confirmation_does_not_authorize_another_domain(bridge):
 b,cid,job=bridge
 b.tool('report_integration_discovery',{'summary':'No exact match','matches':[]},job)
 assert b.tool('write_files',{'domain':'sample_light','files':files()},job)['ok']
 assert not b.tool('write_files',{'domain':'another_light','files':files('another_light')},job)['ok']


def test_snapshot_pruning_keeps_recent_revisions_and_daily_points(bridge):
 from datetime import datetime,timedelta,timezone
 b,_,_=bridge;history=b.manager.history;folder=history.directory('sample_light');folder.mkdir(parents=True)
 now=datetime.now(timezone.utc)
 # Many same-day revisions, plus older daily checkpoints.
 moments=[now+timedelta(microseconds=i) for i in range(130)]+[now-timedelta(days=i) for i in range(1,36)]
 for moment in moments:
  ident=moment.strftime('%Y%m%dT%H%M%S%fZ');(folder/(ident+'.zip')).write_bytes(b'placeholder')
  (folder/(ident+'.json')).write_text(json.dumps({'id':ident,'created':moment.isoformat(),'sha256':'test','source':'staged'}))
 history.prune('sample_light');revisions=history.list('sample_light')
 assert len(revisions)<=130 and len({item['created'][:10] for item in revisions})==30


def test_corrupted_snapshot_cannot_escape_workspace(bridge):
 import zipfile
 b,_,_=bridge;b.manager.write_files('sample_light',files());revision=b.manager.history.list('sample_light')[0]['id']
 path=b.manager.history.directory('sample_light')/(revision+'.zip')
 with zipfile.ZipFile(path,'w') as archive:archive.writestr('../escape.py','bad')
 with pytest.raises(ValueError):b.manager.history.restore('sample_light',revision)
 assert b.manager.read_file('sample_light','__init__.py')['content']=='# v1\n'


def test_retry_endpoint_resumes_same_job_and_rejects_duplicate(tmp_path,monkeypatch):
 import threading
 from fastapi.testclient import TestClient
 from app.main import create_app
 monkeypatch.setenv('HA_INGRESS_ONLY','0');app=create_app(tmp_path/'data',tmp_path/'ha',{})
 conv=app.state.store.new_conversation();job=app.state.jobs.new(conv['id']);app.state.jobs.status(job,'failed');app.state.jobs.fields(job,retryable=True)
 app.state.store.put('recoveries',job,{'session_id':'saved'})
 started=threading.Event();release=threading.Event();calls=[]
 def run(cid,message,ident,resume=False):calls.append((cid,message,ident,resume));started.set();release.wait(5)
 monkeypatch.setattr(app.state.agent,'run',run)
 client=TestClient(app)
 assert client.post('/api/jobs/'+job+'/retry',json={}).status_code==200
 assert started.wait(1) and calls==[(conv['id'],'',job,True)]
 assert client.post('/api/jobs/'+job+'/retry',json={}).status_code==409
 assert app.state.store.get_conversation(conv['id'])['messages']==[]
 release.set()


def test_chat_choice_is_explicit_and_persisted(tmp_path,monkeypatch):
 from fastapi.testclient import TestClient
 from app.main import create_app
 monkeypatch.setenv('HA_INGRESS_ONLY','0');app=create_app(tmp_path/'data',tmp_path/'ha',{})
 monkeypatch.setattr(app.state.agent,'run',lambda *args,**kwargs:None)
 conv=app.state.store.new_conversation();app.state.store.put('discoveries',conv['id'],{'matches':[{'name':'Existing'}],'custom_approved':False})
 client=TestClient(app)
 assert client.post('/api/chat',json={'message':'Build anyway','build_custom_anyway':True}).status_code==400
 assert client.post('/api/chat',json={'conversation_id':conv['id'],'message':'Build my own anyway','build_custom_anyway':True}).status_code==200
 assert app.state.store.records('discoveries')[conv['id']]['custom_approved'] is True


def test_recovery_uses_root_turn_when_last_observed_turn_was_a_subagent(bridge):
 b,_,_=bridge
 def retrieve(ident,**kwargs):return NS(id=ident,status='completed',subagent_id='child' if ident=='child-turn' else None)
 client=NS(beta=NS(agents=NS(sessions=NS(retrieve=lambda sid:NS(status='idle'),turns=NS(retrieve=retrieve,items=NS(list=lambda *args,**kwargs:NS(data=[NS(type='message',role='assistant',id='answer',content=[NS(type='output_text',text='Root answer')])])))))))
 chunks={};assert b._recover_completed_turn(client,'session',['root-turn','child-turn'],chunks)
 assert list(chunks.values())==['Root answer']

def test_intermediate_commentary_is_ordered_and_idempotent(bridge):
 b,cid,job=bridge
 b.jobs.step(job,'before','list_integrations',{})
 b.jobs.finish_step(job,'before',{'ok':True})
 chunks={('message-1',0,0):'I found the relevant files. **Next I will update them.**'}
 b._publish_intermediate(cid,job,chunks)
 b._publish_intermediate(cid,job,chunks)
 b.jobs.step(job,'after','validate_integration',{})
 messages=b.store.get_conversation(cid)['messages']
 assert len(messages)==1
 assert messages[0]['agent_job_id']==job
 steps=b.jobs.get(job)['steps']
 assert steps[0]['after_message']==0
 assert steps[1]['after_message']==1
 assert messages[0]['content']==chunks[('message-1',0,0)]



def test_snapshot_symlink_rejection_uses_integration_error(bridge,monkeypatch):
 from pathlib import Path
 from app.integrations import IntegrationError
 b,_,_=bridge
 root=b.manager.workspace('sample_light');root.mkdir()
 nested=root/'nested';nested.mkdir()
 original=Path.is_symlink
 monkeypatch.setattr(Path,'is_symlink',lambda path:path==nested or original(path))
 with pytest.raises(IntegrationError,match='linked source'):
  b.manager.write_files('sample_light',[{'path':'nested/test.py','content':'x=1'}])
 assert not (nested/'test.py').exists()
