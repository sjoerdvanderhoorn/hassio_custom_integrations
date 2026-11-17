import io,json,stat,zipfile
import pytest
from app.main import create_app
from app.transfers import Transfers
from app.integrations import IntegrationError,MARKER
from fastapi.testclient import TestClient

def archive(files):
 out=io.BytesIO()
 with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
  for name,data in files.items():z.writestr(name,data)
 return out.getvalue()

def component(domain='sample_lamp'):
 return {f'custom_components/{domain}/manifest.json':json.dumps({'domain':domain,'name':'Sample Lamp','version':'1.0.0'}),f'custom_components/{domain}/__init__.py':'# code only\n'}

@pytest.fixture
def setup(tmp_path,monkeypatch):
 monkeypatch.setenv('HA_INGRESS_ONLY','0')
 app=create_app(tmp_path/'data',tmp_path/'ha',{})
 return app,Transfers(app.state.manager,app.state.store,app.state.agent.ha,app.state.installations)

def test_import_share_roundtrip_and_no_overwrite(setup):
 app,t=setup; result=t.import_zip(archive(component()))
 assert result['domain']=='sample_lamp' and not result['installed']
 with pytest.raises(IntegrationError):t.import_zip(archive(component()))
 exported=t.export_zip('sample_lamp')
 with zipfile.ZipFile(io.BytesIO(exported)) as z:
  assert set(z.namelist())==set(component())
 assert not app.state.manager.installed_path('sample_lamp').exists()

@pytest.mark.parametrize('extra',[{'../escape.py':'bad'},{'C:/escape.py':'bad'},{'custom_components/sample_lamp/secrets.yaml':'password: secret'},{'custom_components/sample_lamp/.env':'secret'}])
def test_unsafe_import_has_no_partial_workspace(setup,extra):
 app,t=setup
 with pytest.raises(IntegrationError):t.import_zip(archive(component()|extra))
 assert not app.state.manager.workspace('sample_lamp').exists()

def test_zip_link_and_bomb_rejected(setup):
 _,t=setup;out=io.BytesIO()
 with zipfile.ZipFile(out,'w') as z:
  item=zipfile.ZipInfo('link');item.external_attr=(stat.S_IFLNK|0o777)<<16;z.writestr(item,'/etc/passwd')
 with pytest.raises(IntegrationError):t.import_zip(out.getvalue())
 with pytest.raises(IntegrationError):t.import_zip(archive(component()|{'huge.txt':'a'*160001}))

def test_staged_uninstall_preserves_backup_and_chat(setup):
 app,t=setup;t.import_zip(archive(component()));conv=app.state.store.new_conversation('sample_lamp')
 result=t.uninstall('sample_lamp')
 assert result['phase']=='complete' and not result['restart_required']
 assert not app.state.manager.workspace('sample_lamp').exists()
 assert app.state.store.get_conversation(conv['id'])
 assert (app.state.manager.backups/'sample_lamp'/result['backups'][0]/'manifest.json').exists()

def installed(setup):
 app,t=setup;t.import_zip(archive(component()))
 target=app.state.manager.installed_path('sample_lamp');target.mkdir(parents=True)
 (target/MARKER).write_text('{}');(target/'manifest.json').write_text(json.dumps({'domain':'sample_lamp','name':'Lamp'}))
 return app,t,target

def test_foreign_domain_refused_before_ha_mutations(setup,monkeypatch):
 app,t,target=installed(setup);(target/MARKER).unlink()
 monkeypatch.setattr(t.ha,'entries',lambda *args:pytest.fail('must not contact HA'))
 with pytest.raises(IntegrationError):t.uninstall('sample_lamp')
 assert target.exists()

def test_failed_entry_removal_preserves_source_and_cancels_plan(setup,monkeypatch):
 app,t,target=installed(setup)
 conv=app.state.store.new_conversation('sample_lamp');item=app.state.installations.prepare('sample_lamp',{},conv['id'])
 monkeypatch.setattr(t.ha,'entries',lambda *args:[{'entry_id':'one','domain':'sample_lamp'}])
 monkeypatch.setattr(t.ha,'core',lambda *args,**kwargs:(_ for _ in ()).throw(RuntimeError('Core unavailable')))
 with pytest.raises(RuntimeError):t.uninstall('sample_lamp')
 assert target.exists() and app.state.manager.workspace('sample_lamp').exists()
 assert app.state.installations.get(item['id'])['phase']=='removed'
 assert list(app.state.store.records('removals').values())[-1]['phase']=='interrupted'

def test_endpoints_require_confirmation_and_handle_zip(setup):
 app,t=setup;client=TestClient(app)
 result=client.post('/api/integrations/import',content=archive(component()),headers={'Content-Type':'application/zip'})
 assert result.status_code==200,result.text
 shared=client.get('/api/integrations/sample_lamp/share');assert shared.status_code==200 and 'sample_lamp.zip' in shared.headers['content-disposition']
 assert client.post('/api/integrations/sample_lamp/uninstall',json={}).status_code==400
 assert client.post('/api/integrations/sample_lamp/uninstall',json={'confirmed':True}).status_code==200


def test_successful_installed_uninstall_removes_entries_before_code(setup,monkeypatch):
 app,t,target=installed(setup);remaining=[{'entry_id':'one','domain':'sample_lamp'}];calls=[]
 monkeypatch.setattr(t.ha,'entries',lambda *args:list(remaining))
 def remove(method,path):
  assert target.exists()
  calls.append((method,path));remaining.clear();return {'result':True}
 monkeypatch.setattr(t.ha,'core',remove)
 result=t.uninstall('sample_lamp')
 assert result['restart_required'] and not target.exists()
 assert calls==[('DELETE','/config/config_entries/entry/one')]


def test_chat_uninstall_cannot_bypass_approval(setup,monkeypatch):
 app,t=setup;t.import_zip(archive(component()));bridge=app.state.agent
 bridge.options.update(auto_deploy=True,auto_restart=True)
 conv=app.state.store.new_conversation('sample_lamp');job=app.state.jobs.new(conv['id'])
 seen=[];monkeypatch.setattr(bridge.jobs,'request_approval',lambda *args:seen.append(args) or False)
 result=bridge.tool('uninstall_integration',{'domain':'sample_lamp'},job)
 assert not result['ok'] and seen and app.state.manager.workspace('sample_lamp').exists()


def test_http_file_operations_reject_active_agent(setup):
 app,t=setup;t.import_zip(archive(component()));client=TestClient(app)
 # Starting an HTTP chat exercises the actual active-job guard, without paid requests.
 app.state.agent.run=lambda *args:None
 result=client.post('/api/chat',json={'message':'Review this lamp','domain':'sample_lamp'})
 assert result.status_code==200,result.text
 assert client.get('/api/integrations/sample_lamp/share').status_code==409
 assert client.post('/api/integrations/sample_lamp/uninstall',json={'confirmed':True}).status_code==409
 assert client.post('/api/integrations/import',content=archive(component('other_lamp'))).status_code==409
