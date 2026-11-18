/* Integration-page controls, managed badges and the Add integration choice dialog. */
const ROOT='/api/custom_integrations/engine/';
const ASSETS='/custom_integrations/frontend/';
const previous=window.__customIntegrationsExtension;
if(previous)previous.abort();
const controller=new AbortController();window.__customIntegrationsExtension=controller;
let snapshot=window.__ciManagedSnapshot || null,lastFetch=0,pending=false,modal=null,available=true;
const element=(tag,text)=>{const el=document.createElement(tag);if(text!==undefined)el.textContent=text;return el;};
const host=()=>document.querySelector('home-assistant');
const currentHass=()=>host()?.hass;
async function api(path,options){
  const hass=currentHass();if(!hass?.user?.is_admin)throw Error('Administrator access is required');
  const result=await hass.fetchWithAuth(ROOT+path,options);
  if(!result.ok){let message='Custom Integrations is unavailable';try{message=(await result.json()).detail || message;}catch(_){}throw Error(message);}
  return result;
}
function deepFind(root,tag){
  const direct=root.querySelector(tag);if(direct)return direct;
  for(const child of root.querySelectorAll('*'))if(child.shadowRoot){const found=deepFind(child.shadowRoot,tag);if(found)return found;}
  return null;
}
function go(path){history.pushState(null,'',path);window.dispatchEvent(new CustomEvent('location-changed',{detail:{replace:false}}));}
function openChat(domain){
  if(modal?.isConnected){modal.focus();return;}
  modal=element('ci-chat-modal');modal.domain=domain || null;document.body.append(modal);
}
const themeCSS=`:host{font-family:var(--ha-font-family-body,var(--primary-font-family,Roboto,Arial,sans-serif));color:var(--primary-text-color,#212121);font-size:14px}button,a,select{font:inherit}button{cursor:pointer}button:disabled{opacity:.5;cursor:wait}button:focus-visible,a:focus-visible{outline:2px solid var(--primary-color,#03a9f4);outline-offset:3px}.primary{background:var(--primary-color,#03a9f4);color:var(--text-primary-color,#fff);border:0;border-radius:20px;padding:10px 18px}.error{color:var(--error-color,#db4437);white-space:pre-wrap}`;
function closeTopPopup(){
  const popup=chooser?.isConnected?chooser:modal;
  const dialog=popup?.shadowRoot?.querySelector('dialog');
  if(!dialog?.open)return false;dialog.close();return true;
}
window.addEventListener('keydown',event=>{
  if(event.key==='Escape' && closeTopPopup()){event.preventDefault();event.stopImmediatePropagation();}
},{capture:true,signal:controller.signal});
window.addEventListener('message',event=>{
  if(event.origin===location.origin && event.source===modal?.shadowRoot?.querySelector('iframe')?.contentWindow && event.data?.type==='ci-close-chat')closeTopPopup();
},{signal:controller.signal});
class CIChatModal extends HTMLElement{
  connectedCallback(){
    const root=this.attachShadow({mode:'open'}),style=element('style');style.textContent=themeCSS+`dialog{padding:0;width:min(1120px,calc(100vw - 48px));height:min(900px,calc(100dvh - 48px));max-width:none;max-height:none;border:1px solid var(--divider-color,#ddd);border-radius:24px;background:var(--card-background-color,#fff);color:inherit;box-shadow:0 18px 60px #0005;overflow:hidden}dialog::backdrop{background:#0006}header{display:flex;align-items:center;gap:16px;padding:12px 20px;border-bottom:1px solid var(--divider-color,#ddd);height:40px}h2{font-size:20px;font-weight:500;flex:1;margin:0}header button{border:0;background:transparent;color:inherit;font-size:24px;padding:6px}iframe{display:block;width:100%;height:calc(100% - 65px);border:0;background:var(--primary-background-color,#fafafa)}@media(max-width:650px){dialog{width:100vw;height:100dvh;margin:0;border:0;border-radius:0}header{padding:8px 12px}}`;
    const dialog=element('dialog'),header=element('header'),heading=element('h2',this.domain?'Edit custom integration':'Add Custom Integration');heading.id='ci-chat-heading';dialog.setAttribute('aria-labelledby',heading.id);
    const close=element('button','×');close.setAttribute('aria-label','Close chat');close.title='Close chat. The agent keeps working; use Stop to stop it.';close.onclick=()=>dialog.close();
    header.append(heading,close);const frame=element('iframe');frame.title='Custom Integrations chat';
    frame.src=ASSETS+'chat/index.html'+(this.domain?'?domain='+encodeURIComponent(this.domain):'');dialog.append(header,frame);root.append(style,dialog);
    const css=getComputedStyle(host() || document.documentElement);
    for(const key of ['primary-color','text-primary-color','primary-text-color','secondary-text-color','card-background-color','primary-background-color','divider-color','error-color','ha-font-family-body','primary-font-family']){const value=css.getPropertyValue('--'+key);if(value.trim())this.style.setProperty('--'+key,value);}
    dialog.onclose=()=>{this.remove();modal=null;lastFetch=0;};dialog.showModal();
  }
}
class CIIntegrationActions extends HTMLElement{
  connectedCallback(){this.attachShadow({mode:'open'});this.render();}
  render(){
    if(!this.shadowRoot)return;
    const style=element('style');style.textContent=themeCSS+`:host{display:inline-flex;align-items:center;vertical-align:middle;margin:0 0 0 8px}.split{display:inline-flex;position:relative;align-items:stretch}.split>button{height:var(--ci-action-height,40px);box-sizing:border-box;line-height:20px;padding-top:0;padding-bottom:0}.edit{border-radius:20px 0 0 20px}.toggle{border-radius:0 20px 20px 0;border-left:1px solid #ffffff60;padding:10px 14px}.menu{position:absolute;right:0;top:calc(100% + 6px);z-index:5;min-width:160px;padding:6px;background:var(--card-background-color,#fff);border:1px solid var(--divider-color,#ddd);box-shadow:0 4px 16px #0003;border-radius:12px}.menu button{display:block;text-align:left;width:100%;padding:12px;border:0;border-radius:6px;background:transparent;color:inherit}.menu button:hover{background:var(--secondary-background-color,#eee)}.menu .danger{color:var(--error-color,#db4437)}[hidden]{display:none!important}.error{margin:8px 0 0}`;
    const split=element('div');split.className='split';const edit=element('button','Edit custom integration');edit.className='primary edit';edit.onclick=()=>openChat(this.domain);
    const toggle=element('button','▾');toggle.className='primary toggle';toggle.setAttribute('aria-label','More integration actions');toggle.setAttribute('aria-haspopup','menu');toggle.setAttribute('aria-expanded','false');
    const menu=element('div');menu.className='menu';menu.setAttribute('role','menu');menu.hidden=true;
    const share=element('button','Share'),uninstall=element('button','Uninstall');uninstall.className='danger';for(const button of [share,uninstall])button.setAttribute('role','menuitem');
    const error=element('p');error.className='error';error.setAttribute('role','status');
    const closeMenu=()=>{menu.hidden=true;toggle.setAttribute('aria-expanded','false');};toggle.onclick=()=>{menu.hidden=!menu.hidden;toggle.setAttribute('aria-expanded',String(!menu.hidden));if(!menu.hidden)share.focus();};
    split.onkeydown=event=>{if(event.key==='Escape'){closeMenu();toggle.focus();}if(event.key==='ArrowDown'){event.preventDefault();uninstall.focus();}if(event.key==='ArrowUp'){event.preventDefault();share.focus();}};
    share.onclick=async()=>{share.disabled=true;try{const response=await api(`api/integrations/${encodeURIComponent(this.domain)}/share`);const url=URL.createObjectURL(await response.blob());const link=element('a');link.href=url;link.download=this.domain+'.zip';document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),10000);closeMenu();}catch(e){error.textContent=e.message;}finally{share.disabled=false;}};
    uninstall.onclick=async()=>{if(!window.confirm('Uninstall this custom integration? Its configuration entries, entities and source code will be removed. Code backups and conversations remain. Remove YAML references yourself. A Core restart may be required.'))return;uninstall.disabled=true;try{const response=await api(`api/integrations/${encodeURIComponent(this.domain)}/uninstall`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({confirmed:true})});const result=await response.json();snapshot={...(snapshot || {}),integrations:(snapshot?.integrations || []).filter(item=>item.domain!==this.domain)};lastFetch=0;go('/config/integrations/dashboard');window.alert(result.restart_required?'Uninstalled. Restart Home Assistant Core to finish unloading its code.':'Staged integration removed.');}catch(e){error.textContent=e.message;}finally{uninstall.disabled=false;closeMenu();}};
    menu.append(share,uninstall);split.append(edit,toggle,menu);this.shadowRoot.replaceChildren(style,split,error);
  }
}
let chooser=null;
const nativeBypass=new WeakSet();
function openChoice(button){
  if(chooser?.isConnected)return;
  chooser=element('ci-add-integration-choice');chooser.nativeButton=button;document.body.append(chooser);
}
class CIAddIntegrationChoice extends HTMLElement{
  connectedCallback(){
    const root=this.attachShadow({mode:'open'}),style=element('style');
    style.textContent=themeCSS+`dialog{width:min(480px,calc(100vw - 48px));padding:24px;box-sizing:border-box;border:1px solid var(--divider-color,#ddd);border-radius:24px;background:var(--card-background-color,#fff);color:inherit;box-shadow:0 18px 60px #0005}dialog::backdrop{background:#0006}header{display:flex;align-items:center;gap:16px;margin-bottom:24px}h2{font-size:22px;font-weight:500;flex:1;margin:0}.close{background:transparent;border:0;color:inherit;font-size:24px}.choices{display:grid;gap:12px}.choices button{padding:16px;text-align:left;border-radius:12px}.secondary{background:#fff;border:1px solid var(--divider-color,#ddd);color:#212121}`;
    const dialog=element('dialog'),header=element('header'),title=element('h2','Add integration');title.id='ci-add-title';dialog.setAttribute('aria-labelledby',title.id);
    const close=element('button','×');close.className='close';close.setAttribute('aria-label','Close integration choices');close.onclick=()=>dialog.close();header.append(title,close);
    const choices=element('div');choices.className='choices';
    const create=element('button','Create custom integration');create.className='secondary';create.onclick=()=>dialog.close('custom');
    const brands=element('button','Select from existing brands');brands.className='secondary';brands.onclick=()=>dialog.close('brands');choices.append(create,brands);dialog.append(header,choices);root.append(style,dialog);
    const css=getComputedStyle(host() || document.documentElement);
    for(const key of ['primary-color','primary-text-color','text-primary-color','card-background-color','divider-color','ha-font-family-body']){const value=css.getPropertyValue('--'+key);if(value.trim())this.style.setProperty('--'+key,value);}
    dialog.onclose=()=>{
      const result=dialog.returnValue;this.remove();chooser=null;
      if(result==='custom')openChat(null);
      if(result==='brands'){
        const button=this.nativeButton?.isConnected?this.nativeButton:deepFind(document,'ha-config-integrations-dashboard')?.shadowRoot?.querySelector('ha-button[slot="fab"]');
        if(button){nativeBypass.add(button);try{button.click();}finally{nativeBypass.delete(button);}}
      }
    };dialog.showModal();
  }
}
// Capture before HA's target listener. One explicit bypass replays the original native action.
document.addEventListener('click',event=>{
  const path=event.composedPath();
  const button=path.find(node=>node?.localName==='ha-button' && node.getAttribute('slot')==='fab');
  if(!button || !path.some(node=>node?.localName==='ha-config-integrations-dashboard'))return;
  if(nativeBypass.has(button)){nativeBypass.delete(button);return;}
  if(controller.signal.aborted || !available || !currentHass()?.user?.is_admin || location.pathname!=='/config/integrations/dashboard')return;
  event.preventDefault();event.stopImmediatePropagation();openChoice(button);
},{capture:true,signal:controller.signal});
for(const [name,type] of [['ci-chat-modal',CIChatModal],['ci-integration-actions',CIIntegrationActions],['ci-add-integration-choice',CIAddIntegrationChoice]])if(!customElements.get(name))customElements.define(name,type);
function removeExtensions(){
  const dashboard=deepFind(document,'ha-config-integrations-dashboard'),detail=deepFind(document,'ha-config-integration-page');
  dashboard?.shadowRoot?.querySelectorAll('ci-integrations-section,[data-ci-badge]').forEach(el=>el.remove());
  for(const card of dashboard?.shadowRoot?.querySelectorAll('ha-integration-card') || [])card.shadowRoot?.querySelectorAll('[data-ci-badge]').forEach(el=>el.remove());
  detail?.shadowRoot?.querySelectorAll('ci-integration-actions').forEach(el=>el.remove());
}
async function tick(){
  if(controller.signal.aborted)return;
  try{
    if(!currentHass()?.user?.is_admin){removeExtensions();return;}
    if(Date.now()-lastFetch>5000 && !pending){pending=true;api('api/state').then(response=>response.json()).then(data=>{snapshot=data;window.__ciManagedSnapshot={integrations:data.integrations};available=true;lastFetch=Date.now();scheduleTick();}).catch(()=>{snapshot=null;window.__ciManagedSnapshot=null;available=false;lastFetch=Date.now();removeExtensions();}).finally(()=>pending=false);}
    if(!snapshot || !location.pathname.startsWith('/config/integrations/'))return;
    if(location.pathname==='/config/integrations/dashboard'){
      deepFind(document,'ha-config-integrations-dashboard')?.shadowRoot?.querySelectorAll('ci-integrations-section').forEach(el=>el.remove());
      const dashboard=deepFind(document,'ha-config-integrations-dashboard');
      const managed=new Set(snapshot.integrations.map(item=>item.domain));
      for(const card of dashboard?.shadowRoot?.querySelectorAll('ha-integration-card') || []){
        const domain=card.domain || card.dataset.domain,icons=card.shadowRoot?.querySelector('.icons');
        if(!icons)continue;
        let badge=icons.querySelector('[data-ci-badge]');
        if(!managed.has(domain)){badge?.remove();continue;}
        if(!badge){
          badge=element('span');badge.dataset.ciBadge='';badge.setAttribute('role','img');badge.setAttribute('aria-label','Created with Custom Integrations');badge.title='Created with Custom Integrations';badge.tabIndex=0;
          badge.style.cssText='display:inline-flex;align-items:center;vertical-align:middle;color:var(--primary-color,#03a9f4);width:18px;height:18px;margin-inline-start:4px';
          const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('aria-hidden','true');svg.style.cssText='width:18px;height:18px;fill:currentColor';
          const path=document.createElementNS(svg.namespaceURI,'path');path.setAttribute('d','M12 2 14.8 9.2 22 12 14.8 14.8 12 22 9.2 14.8 2 12 9.2 9.2ZM20 1 20.8 3.2 23 4 20.8 4.8 20 7 19.2 4.8 17 4 19.2 3.2Z');svg.append(path);badge.append(svg);icons.append(badge);
        }
      }
    }else{
      const page=deepFind(document,'ha-config-integration-page'),root=page?.shadowRoot,domain=page?.domain || decodeURIComponent(location.pathname.split('/').pop());
      const managed=snapshot.integrations.some(item=>item.domain===domain);
      let actions=root?.querySelector('ci-integration-actions');
      if(!managed){actions?.remove();return;}
      const header=root?.querySelector('.header');
      const group=header?.querySelector('.actions') || header;
      if(group){if(!actions){actions=element('ci-integration-actions');actions.domain=domain;group.append(actions);}else{if(actions.parentElement!==group)group.append(actions);if(actions.domain!==domain){actions.domain=domain;actions.render();}}}
      if(actions){
        const native=group.querySelector('ha-button,button');
        if(native && !actions.contains(native)){
          const rect=native.getBoundingClientRect();
          if(rect.height>0){actions.style.setProperty('--ci-action-height',rect.height+'px');actions.style.alignSelf='center';}
        }
      }
    }
  }catch(error){console.warn('Custom Integrations could not attach its controls. Native Home Assistant controls are unchanged.');}
  finally{}
}
let scheduled=false;
const watchers=new Map();
function scheduleTick(){
  if(scheduled || controller.signal.aborted)return;scheduled=true;
  requestAnimationFrame(()=>{scheduled=false;if(controller.signal.aborted)return;watchRoots(document);tick();});
}
function watchRoots(root){
  for(const [known,observer] of watchers)if(known.host && !known.host.isConnected){observer.disconnect();watchers.delete(known);}
  if(!watchers.has(root)){const observer=new MutationObserver(scheduleTick);observer.observe(root,{childList:true,subtree:true});watchers.set(root,observer);}
  const routing=new Set(['home-assistant','home-assistant-main','partial-panel-resolver','ha-panel-config']);
  const integrations=new Set(['ha-config-integrations','ha-config-integrations-dashboard','ha-config-integration-page','hass-tabs-subpage','hass-subpage','ha-integration-card']);
  for(const el of root.querySelectorAll('*'))if(el.shadowRoot && (routing.has(el.localName) || (location.pathname.startsWith('/config/integrations/') && integrations.has(el.localName))))watchRoots(el.shadowRoot);
}
window.addEventListener('location-changed',scheduleTick,{signal:controller.signal});
window.addEventListener('popstate',scheduleTick,{signal:controller.signal});
const fallback=setInterval(scheduleTick,1000);
controller.signal.addEventListener('abort',()=>{clearInterval(fallback);for(const observer of watchers.values())observer.disconnect();watchers.clear();removeExtensions();modal?.remove();chooser?.remove();});
watchRoots(document);tick();
