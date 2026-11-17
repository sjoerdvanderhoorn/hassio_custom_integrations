"""Browser contract test: simulated HA shadow DOM with actual extension and modal assets."""
from pathlib import Path
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
import threading,os,json
from playwright.sync_api import sync_playwright,expect
ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'custom_components/custom_integrations/frontend'
PREVIEWS=Path(os.environ.get('UI_PREVIEW_DIR','work/marketplace-previews'));PREVIEWS.mkdir(parents=True,exist_ok=True)
HOST='''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head><body style="margin:0;background:#fafafa;font-family:Arial"><home-assistant style="--primary-color:#03a9f4;--primary-text-color:#212121;--secondary-text-color:#727272;--primary-background-color:#fafafa;--card-background-color:#fff;--divider-color:#ddd;--ha-font-family-body:Arial"></home-assistant><script>
customElements.define('ha-button',class extends HTMLElement{constructor(){super();this.attachShadow({mode:'open'}).innerHTML='<button style="padding:12px"><slot></slot></button>';}});
customElements.define('ha-integration-card',class extends HTMLElement{connectedCallback(){this.domain=this.dataset.domain;this.attachShadow({mode:'open'}).innerHTML='<span class="icons"><span id="icon-custom" role="img" aria-label="Custom integration">◇</span><span id="icon-cloud" role="img" aria-label="Requires Internet">☁</span></span>';}});
customElements.define('ha-config-integrations-dashboard',class extends HTMLElement{constructor(){super();this.attachShadow({mode:'open'}).innerHTML='<style>h2{font:20px Arial;margin:24px}.container{padding:24px}button{padding:12px}</style><hass-tabs-subpage><div slot="toolbar">Search integrations</div><h2 class="section-header">Configured</h2><div class="container"><p>Official integrations</p><ha-integration-card data-domain="parcel_tracker"></ha-integration-card><ha-integration-card data-domain="unmanaged_foreign"></ha-integration-card><ha-button id="native-add" slot="fab">Add integration</ha-button></div></hass-tabs-subpage>';this.shadowRoot.querySelector('#native-add').onclick=()=>{window.nativeAdd=(window.nativeAdd||0)+1;const dialog=document.createElement('dialog');dialog.innerHTML='<h2>Select brand</h2><button>Close brands</button>';dialog.querySelector('button').onclick=()=>{dialog.close();dialog.remove();};document.body.append(dialog);dialog.showModal();};}});
customElements.define('ha-config-integration-page',class extends HTMLElement{constructor(){super();this.domain=location.pathname.split('/').pop();this.attachShadow({mode:'open'}).innerHTML='<style>.container{padding:24px}.header{display:flex;align-items:center;justify-content:space-between;gap:24px;flex-wrap:wrap}button{padding:12px}</style><hass-subpage><div class="container"><div class="header"><h1>Parcel Tracker</h1><div class="actions" style="display:flex;align-items:center;gap:8px"><button id="add-entry">Add entry</button><button id="add-device">Add device</button></div></div><h2>Entities</h2><p>Parcel status: In transit</p><h2>Activity</h2></div></hass-subpage>';for(const id of ['add-entry','add-device'])this.shadowRoot.querySelector('#'+id).onclick=()=>window[id]=(window[id]||0)+1;}});
customElements.define('home-assistant',class extends HTMLElement{constructor(){super();this.attachShadow({mode:'open'});this.hass={user:{is_admin:true},locale:{language:'en'},fetchWithAuth:(path,options={})=>fetch(path,{...options,headers:{...options.headers,Authorization:'Bearer simulated-admin'}})};this.render();window.addEventListener('location-changed',()=>this.render());}render(){this.shadowRoot.replaceChildren(document.createElement(location.pathname.includes('/integration/')?'ha-config-integration-page':'ha-config-integrations-dashboard'));}});
</script><script type="module" src="/custom_integrations/frontend/extension.js"></script></body></html>'''
class Handler(BaseHTTPRequestHandler):
 def do_GET(self):
  if self.path.startswith('/custom_integrations/frontend/'):
   path=BASE/self.path.split('/frontend/')[1].split('?')[0]
   if not path.is_file():self.send_error(404);return
   data=path.read_bytes();mime={'.js':'text/javascript','.css':'text/css','.html':'text/html','.json':'application/json'}.get(path.suffix,'application/octet-stream')
  else:data=HOST.encode();mime='text/html'
  self.send_response(200);self.send_header('Content-Type',mime);self.end_headers();self.wfile.write(data)
 def log_message(self,*args):pass
server=ThreadingHTTPServer(('127.0.0.1',0),Handler);threading.Thread(target=server.serve_forever,daemon=True).start();origin=f'http://127.0.0.1:{server.server_port}'
items=[{'domain':'parcel_tracker','name':'Parcel Tracker','installed':True},{'domain':'school_updates','name':'School Updates','installed':False}]
conversations=[{'id':'first','title':'Parcel setup','domains':['parcel_tracker'],'updated':'2026-11-17T10:00:00Z'},{'id':'last','title':'Add delivery estimate','domains':['parcel_tracker'],'updated':'2026-11-17T12:00:00Z'}]
auth=[];mode={'offline':False,'chat':None,'uninstalled':False,'long':False,'tail':False}
def api(route):
 auth.append(route.request.headers.get('authorization'))
 path=route.request.url.split('/engine/')[1]
 if mode['offline']:return route.fulfill(status=503,json={'detail':'Temporarily unavailable'})
 if path=='api/state':data={'integrations':items,'conversations':conversations,'active_job':None,'installations':[],'ha':{'connected':True,'version':'2026.11'},'settings':{},'api_key_configured':True}
 elif path.startswith('api/conversations/'):
  ident=path.split('/')[-1];conv=next((c for c in conversations if c['id']==ident),{'id':ident,'title':'New request','domains':[]})
  data={**conv,'messages':[{'role':'user','content':'Add a delivery estimate'},{'role':'assistant','content':'Ready','rendered_content':'<h2>How to test</h2><p><strong>Track a parcel.</strong></p>'}],'jobs':[],'installations':[]}
  if mode['long']:data['messages'][-1].update(content='Long response'+str(mode['tail']),rendered_content='<p>Earlier content</p>'*80+('<p>Newest streamed content</p>' if mode['tail'] else ''))
 elif path=='api/chat':mode['chat']=route.request.post_data_json;data={'conversation_id':'last','job_id':'test'}
 elif path.startswith('api/jobs/'):data={'id':'test','status':'done','steps':[],'events':[],'approval':None}
 elif path.endswith('/share'):return route.fulfill(content_type='application/zip',body='code zip')
 elif path.endswith('/uninstall'):
  assert route.request.post_data_json=={'confirmed':True};items[:]=[i for i in items if i['domain']!='parcel_tracker'];mode['uninstalled']=True;data={'restart_required':True}
 else:return route.fulfill(status=404,json={'detail':'Unexpected API route: '+path})
 route.fulfill(json=data)
with sync_playwright() as p:
 browser=p.chromium.launch(executable_path=os.environ.get('BROWSER_EXECUTABLE'),headless=True)
 page=browser.new_page(viewport={'width':1440,'height':1000});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
 page.route('**/api/custom_integrations/engine/**',api);page.goto(origin+'/config/integrations/dashboard')
 expect(page.locator('ci-integrations-section')).to_have_count(0)
 expect(page.locator('ha-integration-card[data-domain="parcel_tracker"] [data-ci-badge]')).to_have_count(1)
 expect(page.locator('ha-integration-card[data-domain="unmanaged_foreign"] [data-ci-badge]')).to_have_count(0)
 expect(page.locator('ha-integration-card #icon-custom')).to_have_count(2)
 page.locator('#native-add').click();expect(page.locator('ci-add-integration-choice dialog')).to_be_visible();assert page.evaluate('window.nativeAdd || 0')==0
 for name in ['Create custom integration','Select from existing brands']:
  assert page.get_by_role('button',name=name,exact=True).evaluate('(el)=>getComputedStyle(el).backgroundColor')=='rgb(255, 255, 255)'
 page.keyboard.press('Escape');expect(page.locator('ci-add-integration-choice')).to_have_count(0)
 page.locator('#native-add').click();expect(page.locator('ci-add-integration-choice dialog')).to_be_visible()
 page.get_by_role('button',name='Close integration choices').click();expect(page.locator('ci-add-integration-choice')).to_have_count(0);assert page.evaluate('window.nativeAdd || 0')==0
 page.locator('#native-add').click();page.get_by_role('button',name='Select from existing brands',exact=True).click()
 expect(page.get_by_role('heading',name='Select brand',exact=True)).to_be_visible();assert page.evaluate('window.nativeAdd')==1
 page.get_by_role('button',name='Close brands').click()
 page.locator('#native-add button').focus();page.keyboard.press('Enter');expect(page.locator('ci-add-integration-choice dialog')).to_be_visible()
 page.screenshot(path=str(PREVIEWS/'add-integration-choice.png'))
 page.get_by_role('button',name='Create custom integration',exact=True).click();expect(page.locator('ci-chat-modal dialog')).to_be_visible()
 frame=page.frame_locator('ci-chat-modal iframe');expect(frame.get_by_role('heading',name='What would you like to build?')).to_be_visible()
 expect(frame.locator('#message')).to_be_focused()
 expect(frame.locator('#message')).to_have_attribute('placeholder','Describe what you need…')
 expect(frame.locator('.chat-header')).to_be_hidden()
 expect(frame.locator('.upload-integration')).to_have_text('Or upload an existing integration')
 expect(frame.get_by_text('Describe a device, share documentation, or ask for a change to an existing custom integration.',exact=True)).to_be_visible()
 frame.locator('#message').press('Escape');expect(page.locator('ci-chat-modal')).to_have_count(0)
 page.locator('#native-add').click();page.get_by_role('button',name='Create custom integration',exact=True).click();frame=page.frame_locator('ci-chat-modal iframe')
 expect(frame.locator('#conversation-picker')).to_be_hidden();expect(frame.locator('aside')).to_have_count(0);expect(frame.locator('#integration-panel')).to_be_hidden()
 frame.locator('#message').fill('Build a parcel tracker');frame.locator('#message').press('Enter');expect(frame.locator('#message')).to_have_value('Build a parcel tracker\n')
 page.get_by_role('button',name='Close chat').click();expect(page.locator('ci-chat-modal')).to_have_count(0)
 page.evaluate("history.pushState(null,'','/config/integrations/integration/parcel_tracker');window.dispatchEvent(new CustomEvent('location-changed'))");expect(page).to_have_url(origin+'/config/integrations/integration/parcel_tracker')
 edit=page.get_by_role('button',name='Edit custom integration',exact=True);expect(edit).to_be_visible()
 assert page.locator('ci-integration-actions').evaluate('(el)=>el.parentElement.classList.contains("actions")')
 add_box=page.locator('#add-entry').bounding_box();edit_box=edit.bounding_box();assert abs((add_box['y']+add_box['height']/2)-(edit_box['y']+edit_box['height']/2))<2
 page.locator('#add-entry').click();page.locator('#add-device').click();assert page.evaluate('window["add-entry"]')==1 and page.evaluate('window["add-device"]')==1
 edit.click();frame=page.frame_locator('ci-chat-modal iframe');expect(frame.locator('#conversation-picker option')).to_have_count(3)
 expect(frame.locator('#chat .integration-landing h1')).to_have_count(0)
 for name,prompt in [('Help me fix an issue…','Help me fix an issue with this integration: '),('Add another device…','Add another device to this integration: '),('Add a new capability…','Add a new capability to this integration: ')]:
  frame.get_by_role('button',name=name,exact=True).click();expect(frame.locator('#message')).to_have_value(prompt);expect(frame.locator('#message')).to_be_focused()
 page.screenshot(path=str(PREVIEWS/'edit-landing.png'))
 frame.locator('#message').press('Escape');expect(page.locator('ci-chat-modal')).to_have_count(0)
 edit.click();frame=page.frame_locator('ci-chat-modal iframe')
 frame.locator('#conversation-picker').select_option('last');expect(frame.locator('#chat h2')).to_have_text('How to test');expect(frame.locator('#chat strong')).to_have_text('Track a parcel.')
 expect(frame.get_by_text('Activity',exact=True)).to_have_count(0);expect(frame.get_by_text('Entities',exact=True)).to_have_count(0)
 frame.locator('#message').fill('Check the estimate');frame.locator('#message').press('Control+Enter');expect(frame.locator('#message')).to_have_value('');assert mode['chat']['conversation_id']=='last'
 page.screenshot(path=str(PREVIEWS/'chat-modal.png'))
 mode['long']=True;expect(frame.locator('#chat p')).to_have_count(80,timeout=8000)
 frame.locator('#chat').evaluate('(el)=>el.scrollTop=0');mode['tail']=True
 expect(frame.get_by_text('Newest streamed content',exact=True)).to_be_in_viewport(timeout=8000)
 page.get_by_role('button',name='Close chat').click()
 page.get_by_role('button',name='More integration actions').click()
 with page.expect_download() as download:page.get_by_role('menuitem',name='Share',exact=True).click()
 assert download.value.suggested_filename=='parcel_tracker.zip'
 # A native rerender must not duplicate controls or remove Add entry/device.
 page.evaluate("document.querySelector('home-assistant').render()")
 expect(page.locator('ci-integration-actions')).to_have_count(1);expect(page.locator('#add-entry')).to_be_visible()
 page.screenshot(path=str(PREVIEWS/'integration-detail.png'))
 page.get_by_role('button',name='More integration actions').click()
 page.on('dialog',lambda dialog:dialog.accept());page.get_by_role('menuitem',name='Uninstall',exact=True).click()
 expect(page).to_have_url(origin+'/config/integrations/dashboard');assert mode['uninstalled']
 expect(page.locator('ci-integrations-section')).to_have_count(0)
 page.screenshot(path=str(PREVIEWS/'integrations-dashboard.png'))
 page.set_viewport_size({'width':390,'height':844});page.locator('#native-add').click();page.get_by_role('button',name='Create custom integration',exact=True).click();expect(page.locator('ci-chat-modal dialog')).to_be_visible();page.screenshot(path=str(PREVIEWS/'mobile-modal.png'));page.get_by_role('button',name='Close chat').click()
 mode['offline']=True
 with page.expect_response(lambda response:'/engine/api/state' in response.url and response.status==503,timeout=10000):pass
 page.locator('#native-add').click();expect(page.get_by_role('heading',name='Select brand',exact=True)).to_be_visible();expect(page.locator('ci-add-integration-choice')).to_have_count(0)
 expect(page.locator('[data-ci-badge]')).to_have_count(0)
 assert auth and all(value=='Bearer simulated-admin' for value in auth),auth
 assert not errors,errors
 browser.close()
server.shutdown();print('Marketplace browser contract checks passed: Add integration choice/cancel/keyboard/exact native replay, no custom overview section, grouped native add/edit controls, automatic streaming scroll, chat modal/history/Markdown/shortcuts, authenticated Share/Uninstall, staged integration, rerender recovery, mobile layout and failure fallback.')
