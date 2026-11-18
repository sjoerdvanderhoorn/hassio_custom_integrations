/* Untrusted text uses textContent. Assistant Markdown uses server-sanitized HTML only. */

(async () => {

  const $ = id => document.getElementById(id);

  const english = {

    togglePanel:'Toggle integration details', stop:'Stop agent', stopping:'Stopping…', stopped:'Stopped', stop_unconfirmed:'Stop not confirmed — retry Stop', paused:'Installation paused', actionRequired:'Action required', thinking:'Thinking', steer:'Send a follow-up to guide the agent…', starting:'The agent is starting. You can send a follow-up when it is ready.',

    resumeLast:'Continue with last conversation:', addDevice:'Add another device…', addCapability:'Add a new capability…', devicePrompt:'Add another device to this integration: ', capabilityPrompt:'Add a new capability to this integration: ', fixIssue:'Help me fix an issue…', fixPrompt:'Help me fix an issue with this integration: ', manage:'Manage this integration', noConversations:'No conversations yet.', activity:'Activity', noActivity:'No activity found in the last 24 hours.', activityUnavailable:'Activity is unavailable in Home Assistant.', activityLimited:'Showing recent activity; results are limited.', logs:'Logs', logsLoading:'Loading logs…', logsUnavailable:'Logs are not available from Home Assistant.', noLogs:'No matching integration log lines found.', logsDescription:'Recent raw integration log lines, filtered by integration and with best-effort credential redaction.',

    conversations:'Conversations', integrations:'Integrations', newIntegration:'New integration',

    welcome:'What would you like to build?', upload:'Or upload an existing integration', share:'Share', uninstall:'Uninstall', integrationActions:'Integration actions', intro:'Describe a device, share documentation, or ask for a change to an existing custom integration.',

    message:'Describe what you need', placeholder:'Describe what you need…', details:'Integration details', close:'Close',

    select:'Select an integration or conversation to see its details.', empty:'No generated integrations yet.',

    noRelated:'No integrations are linked to this conversation yet.', installed:'Installed', notInstalled:'Not installed',

    configured:'Configured', notConfigured:'Not configured', unknown:'Unknown', entities:'Entities', noEntities:'No registered entities yet.',

    noState:'No current state', disabled:'Disabled', brightness:'Brightness', yes:'Yes', no:'No',

    openHA:'Open in Home Assistant', finishHA:'Continue setup in Home Assistant', updated:'Updated',

    refreshError:'Cannot refresh integration details. Displayed data may be out of date.',

    connectionError:'Cannot reach the app. Retrying…', keyMissing:'OpenAI API key not configured', haOffline:'Home Assistant unavailable',

    working:'Working', done:'Completed', failed:'Failed', interrupted:'Interrupted', approval_required:'Waiting for approval',

    previous:'previous steps hidden', diagnostics:'Technical details', approve:'Approve', deny:'Deny', diff:'Code changes',

    interruptedHelp:'This task was interrupted by an app restart. Its actions have not been replayed. Send a message to continue.',

    restart:'Approve Core restart', continueInstall:'I have checked Home Assistant — continue',

    restartConfirm:'Restart Home Assistant Core now? Automations will be temporarily unavailable. Configuration will continue automatically.',

    continueConfirm:'Continue this installation after checking Home Assistant? This will not reinstall code or request another restart.',

    installation:'Installation', prepared:'Ready to install', deploying:'Installing code', awaiting_restart:'Awaiting restart approval',

    restart_requested:'Requesting restart', waiting_core:'Waiting for Home Assistant', configuring:'Configuring integration',

    submitting:'Applying configuration', reconciling:'Checking interrupted configuration', verifying:'Verifying entities',

    needs_input:'Your input is needed', complete:'Installation verified', cancelled:'Cancelled',

    manual_setup:'Finish setup in Home Assistant', handing_over:'Opening Home Assistant setup',

    settings:'Settings', settingsHelp:"Change these settings on the app's Configuration page in Home Assistant.",

    auto_deploy:'Automatically deploy', auto_restart:'Automatically restart Core',

    noConfigured:'No config entries', newConversation:'New conversation', send:'Send message', toggleNavigation:'Toggle navigation',

  };

  let language='en', messages={...english};

  try {

    const requested=new URLSearchParams(location.search).get('lang');

    const host=window.parent.document.querySelector('home-assistant');

    language=requested || host?.hass?.locale?.language || host?.hass?.language || 'en';

  } catch (_) { language=new URLSearchParams(location.search).get('lang') || 'en'; }

  if (!/^[a-z]{2,3}(?:-[A-Za-z]{2,4})?$/.test(language)) language='en';

  let effectiveLanguage='en';

  try { const response=await fetch(`static/translations/${language}.json`); if(response.ok) {messages={...english,...await response.json()};effectiveLanguage=language;} } catch(_) {}

  const t=key=>messages[key] || english[key] || key;

  document.documentElement.lang=effectiveLanguage;

  document.querySelectorAll('[data-i18n]').forEach(el=>el.textContent=t(el.dataset.i18n));

  $('message').placeholder=t('placeholder');

  for (const [id,key] of [['new','newIntegration'],['send','send'],['menu','toggleNavigation'],['toggle-panel','togglePanel'],['stop','stop'],['close-integrations','close']]) $(id).setAttribute('aria-label',t(key));

  const node=(tag,cls,text)=>{const el=document.createElement(tag);if(cls)el.className=cls;if(text!==undefined)el.textContent=text;return el;};

  async function request(url,body) {

    const response=await fetch(url,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});

    if(!response.ok) { let detail='Request failed'; try {const value=await response.json();detail=typeof value.detail==='string'?value.detail:detail;}catch(_){} throw Error(detail); }

    return response.json();

  }

  const state={integration:null,conversation:null,context:null,domains:[],activeJob:null,conversations:[],integrations:[],settings:{},busy:false,selection:0,chatKey:'',detailsKey:'',polling:false,currentJob:null,messageCount:0,stopSending:false};

  function svgIcon(path) {

    const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('aria-hidden','true');

    const shape=document.createElementNS(svg.namespaceURI,'path');shape.setAttribute('d',path);svg.append(shape);return svg;

  }

  $('send').append(svgIcon('M3 3 22 12 3 21 3 14 16 12 3 10Z'));

  $('stop').append(svgIcon('M7 7H17V17H7Z'));

  $('toggle-panel').append(svgIcon('M3 4H21V20H3ZM5 6V18H14V6ZM16 6V18H19V6Z'));

  function haHost() {

    let current=window;

    for(let i=0;i<6;i++){try{const host=current.document.querySelector('home-assistant');if(host)return {host,window:current};if(current===current.parent)break;current=current.parent;}catch(_){break;}}

    return null;

  }

  function moreInfo(entityId) {

    const context=haHost();

    if(context){context.host.dispatchEvent(new context.window.CustomEvent('hass-more-info',{detail:{entityId},bubbles:true,composed:true}));return;}

    const url=new URL('/config/entities',location.origin);url.searchParams.set('more-info-entity-id',entityId);window.top.location.href=url.href;

  }

  function resizeComposer() {

    const input=$('message');input.style.height='auto';input.style.height=Math.min(input.scrollHeight,240)+'px';input.style.overflowY=input.scrollHeight>240?'auto':'hidden';

  }

  function updateComposer(job=state.currentJob) {

    state.currentJob=job || null;

    const active=job && ['working','approval_required','stopping','stop_unconfirmed'].includes(job.status);

    state.activeJob=active?job.id:null;

    const blocked=state.busy || (active && job.can_steer!==true);

    $('message').disabled=!!blocked;$('send').disabled=!!blocked || !$('message').value.trim();

    $('message').placeholder=active?t(['stopping','stop_unconfirmed'].includes(job.status)?job.status:job.can_steer?'steer':'starting'):t('placeholder');

    $('stop').hidden=!active;$('stop').disabled=state.stopSending || job?.status==='stopping';

    $('composer').setAttribute('aria-busy',String(!!active));

  }

  const integrationName=domain=>state.integrations.find(item=>item.domain===domain)?.name || domain;

  function remember() {try{localStorage.setItem('aib.selection.v3',JSON.stringify({conversation:state.conversation,context:state.integration}));}catch(_){}}

  function icon(domain) {

    const img=node('img','brand'); img.alt='';img.src=`api/integrations/${encodeURIComponent(domain)}/icon`;

    img.onerror=()=>{img.onerror=null;img.src='static/integration.svg';};return img;

  }

  function haLink(path,label) {

    const link=node('a','ha-link',label);link.href=new URL(path,location.origin).href;link.target='_top';return link;

  }

  function showPanel(open) { $("integration-panel").hidden=true; return;

    open=!!open && state.domains.length>0;$('toggle-panel').disabled=!state.domains.length;$('show-details').hidden=!state.domains.length;

    $('integration-panel').hidden=!open;document.body.classList.toggle('details-open',open);

    $('show-details').setAttribute('aria-expanded',String(open));$('toggle-panel').setAttribute('aria-expanded',String(open));

  }

  let navKey='';

  function updateConversationPicker(){
    const picker=$('conversation-picker');if(!picker)return;
    picker.hidden=!new URLSearchParams(location.search).get('domain');
    const domain=state.integration || state.domains[0] || new URLSearchParams(location.search).get('domain');
    const related=state.conversations.filter(c=>c.domains.includes(domain));
    const key=JSON.stringify([related,state.conversation]);if(picker.dataset.key===key)return;picker.dataset.key=key;
    picker.replaceChildren(new Option('New conversation',''));
    for(const conversation of related)picker.add(new Option(conversation.title,conversation.id));
    if(state.conversation && !related.some(c=>c.id===state.conversation))picker.add(new Option('Current conversation',state.conversation));
    picker.value=state.conversation || '';
  }
  $('conversation-picker').onchange=()=>{const id=$('conversation-picker').value;const domain=state.integration || state.domains[0] || new URLSearchParams(location.search).get('domain');if(id)openConversation(id,domain);else if(domain)openIntegration(domain);else $('new').click();};

  function nav() { updateConversationPicker(); return;

    const key=JSON.stringify([state.conversations,state.integrations,state.conversation,state.integration]);

    if(key===navKey)return;

    navKey=key;

    const integrationFocus=document.activeElement?.dataset?.domain;

    $('integrations').replaceChildren();

    for(const item of state.integrations) {

      const button=node('button',item.domain===state.integration?'selected':'');button.dataset.domain=item.domain;

      button.append(icon(item.domain),node('span','',item.name || item.domain));button.onclick=()=>openIntegration(item.domain);$('integrations').append(button);

      if(integrationFocus===item.domain)button.focus();

    }

    if(!state.integrations.length)$('integrations').append(node('p','hint',t('empty')));

  }

  function message(role,text,rendered) {

    const el=node('div',`msg ${role}`);

    if(role==='assistant' && typeof rendered==='string') {

      // Only app.markdown.render_markdown supplies this field; raw agent HTML is never inserted.

      el.classList.add('markdown');el.innerHTML=rendered;

      for(const link of el.querySelectorAll('a')){link.target='_blank';link.rel='noopener noreferrer';}

    } else el.textContent=text;

    $('chat').append(el);

  }

  function disclosureIcon() {
    const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
    svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('aria-hidden','true');svg.classList.add('disclosure-icon');
    const path=document.createElementNS(svg.namespaceURI,'path');path.setAttribute('d','m9 5 7 7-7 7');svg.append(path);return svg;
  }

  function toolStep(step) {

    const details=node('details','tool-step '+step.status);details.dataset.expandKey='step:'+step.id;const summary=node('summary');summary.title='Show action details';

    summary.append(node('span','step-indicator',step.status==='working'?'◌':step.status==='done'?'✓':step.status==='failed'?'!':'○'),node('span','step-label',step.label),node('span','step-status',t(step.status)));

    summary.append(disclosureIcon());
    details.append(summary,node('pre','diagnostics',JSON.stringify({tool:step.tool,started:step.started,finished:step.finished,arguments:step.arguments,result:step.result},null,2)));

    return details;

  }

  function progress(job) {

    if(!(job.steps || []).length && job.status==='done' && !(job.events || []).some(event=>['error','approval','retry'].includes(event.kind)))return;

    const group=node('section','progress-group');group.dataset.job=job.id;

    const steps=job.steps || [];

    if(steps.length) {

      const current=steps.find(step=>step.status==='working') || steps[steps.length-1];



      const earlier=steps.filter(step=>step.id!==current.id);

      if(earlier.length) {

        const history=node('details','previous-steps');history.dataset.history=job.id;history.dataset.expandKey='history:'+job.id+':'+(steps[0].after_message ?? job.after_message);

        const toggle=node('summary','');toggle.append(disclosureIcon(),node('span','',`${earlier.length} ${t('previous')}`));history.append(toggle);

        earlier.forEach(step=>history.append(toolStep(step)));group.append(history);

      }

    }

    if(steps.length)group.append(toolStep(steps.find(step=>step.status==='working') || steps[steps.length-1]));

    if(job.status==='interrupted')group.append(node('p','status-note',t('interruptedHelp')));

    if(job.status==='working') {

      const thinking=node('div','thinking-indicator');thinking.setAttribute('role','status');thinking.setAttribute('aria-label',t('thinking'));

      for(let i=0;i<3;i++)thinking.append(node('span','thinking-dot'));group.append(thinking);

    } else if(!['done','failed','interrupted'].includes(job.status))group.append(node('p','status-note',t(job.status)));

    for(const event of job.events || [])if(['error','approval','retry'].includes(event.kind))group.append(node('p',event.kind==='error'?'error':'hint',event.message));

    if(job.retryable && job.status==='failed'){
      const retry=node('button','primary-button retry-stream','Retry');retry.type='button';
      retry.onclick=async()=>{retry.disabled=true;try{const result=await request(`api/jobs/${job.id}/retry`,{});state.activeJob=result.job_id;await refresh();}catch(error){$('connection-error').textContent=error.message;retry.disabled=false;}};
      group.append(node('p','hint','This request might be too big to handle all at once. Retry reconnects to the same session; you can also send a smaller follow-up.'),retry);
    }
    $('chat').append(group);

  }

  let scrollPending=false;
  function scrollChatToBottom(){
    if(scrollPending)return;scrollPending=true;
    requestAnimationFrame(()=>requestAnimationFrame(()=>{scrollPending=false;$('chat').scrollTop=$('chat').scrollHeight;}));
  }
  new MutationObserver(scrollChatToBottom).observe($('chat'),{childList:true,subtree:true,characterData:true});
  if(window.ResizeObserver)new ResizeObserver(scrollChatToBottom).observe($('chat'));
  document.fonts?.ready.then(scrollChatToBottom);

  function renderConversation(conv) {

    const key=JSON.stringify([conv.messages,conv.jobs,conv.domains,conv.installations,state.integrations]);

    if(key===state.chatKey)return;

    const expanded=[...$('chat').querySelectorAll('details[open]')].map(el=>el.dataset.expandKey).filter(Boolean);

    const newMessage=conv.messages.length!==state.messageCount;state.messageCount=conv.messages.length;

    const previousScroll=$('chat').scrollTop;

    state.chatKey=key;$('chat').replaceChildren();

    const jobs=conv.jobs || [], installations=conv.installations || [];

    const installAt=index=>installations.filter(item=>Math.min(conv.messages.length,Math.max(0,item.after_message ?? 1))===index).forEach(item=>$('chat').append(installationCard(item)));

    installAt(0);

    for(let i=0;i<conv.messages.length;i++) {

      const msg=conv.messages[i];message(msg.role,msg.content,msg.rendered_content);
      if(msg.integration_discovery){
        const card=node('section','discovery-card');card.append(node('strong','','Existing integration options'),node('p','hint',msg.integration_discovery.summary));
        for(const match of msg.integration_discovery.matches){
          const link=node('a','',match.name);try{const url=new URL(match.url);if(url.protocol==='https:' && !url.username && !url.password){link.href=url.href;link.target='_blank';link.rel='noopener noreferrer';}}catch(_){}
          card.append(link,node('p','',match.reason));
          if(match.setup_available){const setup=node('a','existing-setup','Set up '+match.name);setup.href='/config/integrations/add?domain='+encodeURIComponent(match.domain);setup.target='_top';card.append(setup);}else card.append(node('p','hint','Follow its documentation to install it before starting Home Assistant setup.'));
        }
        const own=node('button','secondary-button','Build my own anyway');own.type='button';own.onclick=async()=>{
          own.disabled=true;try{const result=await request('api/chat',{conversation_id:conv.id,message:'I understand an existing integration is available. Build my own integration anyway.',build_custom_anyway:true,submission_id:crypto.randomUUID()});state.conversation=result.conversation_id;state.activeJob=result.job_id;await refresh();}catch(error){$('connection-error').textContent=error.message;own.disabled=false;}
        };card.append(own);$('chat').append(card);
      }

      for(const job of jobs) {

        const steers=conv.messages.map((msg,index)=>(msg.job_id===job.id || msg.agent_job_id===job.id)?index+1:0);

        const currentAnchor=Math.max(job.after_message,...steers);

        const groupSteps=(job.steps || []).filter(step=>(step.after_message ?? job.after_message)===i+1);

        if(groupSteps.length || currentAnchor===i+1)progress({...job,steps:groupSteps,status:currentAnchor===i+1?job.status:'done',events:currentAnchor===i+1?job.events:[]});

      }

      installAt(i+1);

    }

    for(const job of jobs.filter(job=>!job.after_message || job.after_message>conv.messages.length))progress(job);

    for(const el of $('chat').querySelectorAll('details'))if(expanded.includes(el.dataset.expandKey))el.open=true;

    const related=(conv.domains || []).filter(domain=>state.integrations.some(item=>item.domain===domain));

    const previous=state.integration;

    state.integration=related.includes(state.integration)?state.integration:related[0] || null;

    state.domains=state.integration?[state.integration]:[];

    if(!state.domains.length)showPanel(false);else if(!previous)showPanel(true);

    remember();nav();

    const active=jobs.find(job=>['working','approval_required','stopping','stop_unconfirmed'].includes(job.status));

    updateComposer(active || null);

    approval(active);

    scrollChatToBottom();

  }

  function approval(job) {

    $('pending').replaceChildren();

    if(!job?.approval)return;

    const value=job.approval;const box=node('section','approval requires-action');box.setAttribute('role','alert');box.append(node('div','action-label',t('actionRequired')),node('strong','',value.title));

    const disclosure=node('details');disclosure.append(node('summary','',t('diagnostics')),node('pre','diagnostics',JSON.stringify(value.details,null,2)));box.append(disclosure);

    for(const decision of ['approve','deny']) {

      const button=node('button',decision==='approve'?'primary-button':'secondary-button',t(decision));button.onclick=async()=>{

        button.disabled=true;try{await request(`api/jobs/${job.id}/approve`,{request_id:value.id,decision});await refresh();}catch(error){$('connection-error').textContent=error.message;button.disabled=false;}

      };box.append(button);

    }

    $('pending').append(box);

  }

  function installationCard(item) {

    const card=node('section','installation-card'+(['needs_input','awaiting_restart','manual_setup','paused'].includes(item.phase)?' requires-action':''));card.dataset.installation=item.id;card.append(node('strong','',`${t('installation')}: ${integrationName(item.domain)}`),node('div','phase '+item.phase,t(item.phase)),node('p','',item.message));

    const details=node('details');details.append(node('summary','',t('diagnostics')),node('pre','diagnostics',JSON.stringify({phase:item.phase,step:item.step_id,error:item.error,history:item.history},null,2)));card.append(details);

    if(['needs_input','interrupted','manual_setup'].includes(item.phase)) {

      const button=node('button','primary-button',t('finishHA'));

      button.onclick=async()=>{button.disabled=true;try{const result=await request(`api/installations/${item.id}/action`,{action:'handoff',confirmed:true});window.top.location.href=new URL(result.path,location.origin).href;}catch(error){$('connection-error').textContent=error.message;button.disabled=false;}};

      card.append(button);

    }

    const action=item.phase==='awaiting_restart'?'restart':['needs_input','interrupted','paused'].includes(item.phase)?'continue':null;

    if(action) {

      const button=node('button',action==='restart' || item.phase==='paused'?'primary-button':'secondary-button',t(action==='restart'?'restart':'continueInstall'));

      button.onclick=async()=>{if(!window.confirm(t(action==='restart'?'restartConfirm':'continueConfirm')))return;button.disabled=true;try{await request(`api/installations/${item.id}/action`,{action,confirmed:true});await refresh();}catch(error){$('connection-error').textContent=error.message;button.disabled=false;}};card.append(button);

    }

    return card;

  }

  async function integrationDetails() { return;

    const selection=state.selection, domains=[...state.domains];

    if(!domains.length){$('integration-details').replaceChildren(node('p','hint',t(state.conversation?'noRelated':'select')));state.detailsKey='';return;}

    try {

      const values=await Promise.all(domains.map(domain=>request(`api/integrations/${encodeURIComponent(domain)}`)));

      if(selection!==state.selection)return;

      const key=JSON.stringify([values,state.conversations,state.conversation]);if(key===state.detailsKey){refreshExtras(values);return;}state.detailsKey=key;

      $('integration-details').replaceChildren();

      for(const data of values) {

        const card=node('section','integration-card');const heading=node('h2'),title=haLink(data.integration_path || `/config/integrations/integration/${encodeURIComponent(data.domain)}`,'');title.className='integration-title-link';title.append(icon(data.domain),node('span','',data.name));heading.append(title);
        const actions=node('details','integration-actions'),summary=node('summary','','⋮');summary.title=t('integrationActions');summary.setAttribute('aria-label',t('integrationActions'));actions.append(summary);
        const menu=node('div','integration-actions-menu');
        const share=node('a','menu-action',t('share'));share.href=`api/integrations/${encodeURIComponent(data.domain)}/share`;share.download=`${data.domain}.zip`;menu.append(share);
        const remove=node('button','menu-action danger',t('uninstall'));remove.type='button';remove.onclick=async()=>{
          if(!window.confirm('Uninstall this integration? Configuration entries, entities and source code will be removed. Code backups and conversations remain. Remove any YAML configuration yourself. A Core restart may be required.'))return;remove.disabled=true;
          try{const result=await request(`api/integrations/${encodeURIComponent(data.domain)}/uninstall`,{confirmed:true});state.integration=null;state.context=null;state.domains=[];state.conversation=null;state.chatKey='';showPanel(false);newLanding();await refresh();$('connection-error').textContent=result.restart_required?'Uninstalled. Restart Home Assistant Core to finish unloading its code.':'Staged integration removed.';}
          catch(error){$('connection-error').textContent=error.message;remove.disabled=false;}
        };menu.append(remove);actions.append(menu);heading.append(actions);card.append(heading);

        card.append(node('p',data.installed?'installed':'hint',`${data.installed?'✓ ':''}${t(data.installed?'installed':'notInstalled')}`));

        const entries=data.entries;

        const history=node('nav','side-conversations');history.setAttribute('aria-label',t('conversations'));history.dataset.conversations=data.domain;

        card.append(node('h3','',t('conversations')));

        const related=conversationsFor(data.domain);

        if(!related.length)history.append(node('p','hint',t('noConversations')));

        for(const conversation of related){const button=node('button',conversation.id===state.conversation?'selected':'',conversation.title);button.dataset.conversation=conversation.id;button.onclick=()=>openConversation(conversation.id,data.domain);history.append(button);}

        card.append(history);

        card.append(node('h3','',t('entities')));

        if(data.entities===null)card.append(node('p','error',t('unknown')));

        else if(!data.entities.length)card.append(node('p','hint',t('noEntities')));

        else for(const entity of data.entities) {

          const attrs=entity.attributes || {}, row=node('button','entity');row.type='button';row.dataset.entity=entity.entity_id;row.onclick=()=>moreInfo(entity.entity_id);

          const label=node('div','entity-name'), entityIcon=node('span','entity-icon');

          entityIcon.append(svgIcon(entity.entity_id.startsWith('light.')?'M9 18h6v2H9Zm3-16a7 7 0 0 0-4 12.74V17h8v-2.26A7 7 0 0 0 12 2Zm2 11.6V15h-4v-1.4l-.7-.47a5 5 0 1 1 5.4 0Z':'M4 4h16v16H4Zm2 2v12h12V6Zm2 9h2v2H8Zm3-4h2v6h-2Zm3-3h2v9h-2Z'));

          label.append(entityIcon,node('span','',entity.display_name || attrs.friendly_name || entity.entity_id));row.append(label);

          let value=entity.state===null?t('noState'):entity.state;

          if(attrs.unit_of_measurement)value+=' '+attrs.unit_of_measurement;

          if(attrs.brightness!==undefined && entity.state==='on')value+=' · '+Math.round(attrs.brightness/255*100)+'%';

          row.append(node('div','entity-value',value));

          if(entity.disabled_by)row.append(node('small','hint',t('disabled')));

          row.setAttribute('aria-label',`${entity.display_name || attrs.friendly_name || entity.entity_id}: ${value}`);card.append(row);

        }

        if(Object.keys(data.errors || {}).length)card.append(node('p','error',t('refreshError')));



        const activity=node('section','activity-section');activity.dataset.activity=data.domain;activity.append(node('h3','',t('activity')),node('p','hint',t('logsLoading')));card.append(activity);

        $('integration-details').append(card);

      }

      refreshExtras(values);$('integration-error').textContent='';

    } catch(_){if(selection===state.selection)$('integration-error').textContent=t('refreshError');}

  }

  function conversationsFor(domain){return state.conversations.filter(conv=>(conv.domains || []).includes(domain)).sort((a,b)=>(b.updated || '').localeCompare(a.updated || ''));}

  let landingKey='';

  function renderLanding(domain){

    const related=conversationsFor(domain),key=JSON.stringify([domain,related]);

    if($('chat').querySelector('.integration-landing') && key===landingKey)return;

    landingKey=key;const landing=node('section','integration-landing');

    if(related.length){const last=related[0],resume=node('button','resume-conversation',`${t('resumeLast')} ${last.title}`);resume.onclick=()=>openConversation(last.id,domain);landing.append(resume);}

    const suggestions=node('div','chat-suggestions');
    for(const [label,prompt] of [['fixIssue','fixPrompt'],['addDevice','devicePrompt'],['addCapability','capabilityPrompt']]){
      const button=node('button','issue-suggestion',t(label));button.type='button';
      button.onclick=()=>{$('message').value=t(prompt);resizeComposer();updateComposer();$('message').focus();$('message').setSelectionRange($('message').value.length,$('message').value.length);};suggestions.append(button);
    }
    landing.append(suggestions);$('chat').replaceChildren(landing);

  }

  const extras=new Map();

  function refreshExtras(values){

    for(const data of values){

      const cached=extras.get(data.domain);

      if(cached?.value)renderExtras(data,cached.value);

      if(cached?.pending || cached && Date.now()-cached.time<30000)continue;

      const entry={time:Date.now(),pending:true,value:cached?.value};extras.set(data.domain,entry);

      request(`api/integrations/${encodeURIComponent(data.domain)}/activity`).then(result=>{entry.pending=false;entry.value=result;renderExtras(data,result);}).catch(()=>{entry.pending=false;entry.value={available:false,events:[],logs_available:false};renderExtras(data,entry.value);});

    }

  }

  function renderExtras(data,result){

    const container=[...document.querySelectorAll('[data-activity]')].find(el=>el.dataset.activity===data.domain);if(!container)return;

    container.replaceChildren(node('h3','',t('activity')));

    const names=new Map((data.entities || []).map(entity=>[entity.entity_id,entity.display_name || entity.attributes?.friendly_name || entity.entity_id]));

    if(!result.available)container.append(node('p','hint',t('activityUnavailable')));

    else if(!result.events?.length)container.append(node('p','hint',t('noActivity')));

    else {

      const list=node('ol','activity-list');

      for(const event of result.events){

        const row=node('li','activity-event'),title=node('div','',names.get(event.entity_id) || event.name || data.name);

        row.append(title,node('div','hint',event.message || event.state || [event.context_domain,event.context_service].filter(Boolean).join('.')));

        const date=new Date(typeof event.when==='number'?event.when*1000:event.when),time=node('time','hint',Number.isNaN(date.getTime())?'':date.toLocaleString(document.documentElement.lang));if(!Number.isNaN(date.getTime()))time.dateTime=date.toISOString();row.append(time);list.append(row);

      }

      container.append(list);

    }

    if(result.truncated)container.append(node('p','hint',t('activityLimited')));

    if(result.logs_available){const logs=node('button','logs-button',t('logs'));logs.onclick=()=>openLogs(data.domain);container.append(logs);}

  }

  let logsGeneration=0;

  async function openLogs(domain){

    const generation=++logsGeneration;

    $('logs-title').textContent=`${t('logs')}: ${integrationName(domain)}`;$('logs-description').textContent=t('logsDescription');$('raw-logs').textContent=t('logsLoading');$('logs-dialog').showModal();

    try{const data=await request(`api/integrations/${encodeURIComponent(domain)}/logs`);if(generation===logsGeneration && $('logs-dialog').open)$('raw-logs').textContent=data.logs || t('noLogs');}catch(_){if(generation===logsGeneration && $('logs-dialog').open)$('raw-logs').textContent=t('logsUnavailable');}

  }

  $('close-logs').onclick=()=>{logsGeneration++;$('logs-dialog').close();};

  async function openConversation(id,domain=state.integration) {

    state.integration=domain;

    state.messageCount=0;state.selection++;state.conversation=id;state.context=null;state.activeJob=null;state.chatKey='';state.detailsKey='';$('chat').replaceChildren();$('pending').replaceChildren();

    state.domains=[];remember();document.body.classList.remove('menu-open');

    try {const selection=state.selection,conv=await request(`api/conversations/${encodeURIComponent(id)}`);if(selection!==state.selection)return;$('chat-title').textContent=conv.title;renderConversation(conv);showPanel(true);nav();await integrationDetails();}catch(error){$('connection-error').textContent=error.message;}

  }

  function openIntegration(domain) {

    state.integration=domain;

    state.messageCount=0;updateComposer(null);state.selection++;state.conversation=null;state.context=domain;state.domains=[domain];state.activeJob=null;state.chatKey='';state.detailsKey='';

    $('chat').replaceChildren();$('pending').replaceChildren();$('chat-title').textContent=integrationName(domain);$('message').value='';resizeComposer();renderLanding(domain);

    remember();document.body.classList.remove('menu-open');showPanel(true);nav();integrationDetails();$('message').focus();

  }

  async function refresh() {

    if(state.polling)return;state.polling=true;const selection=state.selection;

    try {

      const data=await request('api/state');state.integrations=data.integrations;state.conversations=data.conversations;state.settings=data.settings;state.activeSummary=data.active_job;

      nav();if(!state.conversation && state.integration)renderLanding(state.integration);$('ha-status').textContent=data.ha.connected?'Home Assistant '+(data.ha.version || ''):t('haOffline');$('key-status').textContent=data.api_key_configured?'':t('keyMissing');

      if(state.conversation) {const conv=await request(`api/conversations/${encodeURIComponent(state.conversation)}`);if(selection===state.selection)renderConversation(conv);}

      if(selection===state.selection){if(!$('integration-panel').hidden)await integrationDetails();}

      $('connection-error').textContent='';

    }catch(_){$('connection-error').textContent=t('connectionError');}finally{state.polling=false;}

  }

  $('composer').onsubmit=async event=>{

    event.preventDefault();if(state.busy || $('message').disabled)return;

    const text=$('message').value.trim();if(!text)return;

    state.busy=true;updateComposer();

    try {

      const response=await request('api/chat',{conversation_id:state.conversation,message:text,domain:state.context,submission_id:submission(text)});

      $('message').value='';lastSubmission=null;resizeComposer();state.conversation=response.conversation_id;state.context=null;state.activeJob=response.job_id;state.chatKey='';

      await openConversation(response.conversation_id);await refresh();

    }catch(error){$('connection-error').textContent=error.message;}finally{state.busy=false;updateComposer();}

  };

  function newLanding(){
    const landing=node('div','welcome');landing.append(node('h1','',t('welcome')),node('p','',t('intro')));
    const upload=node('button','upload-integration',t('upload'));upload.type='button';upload.onclick=()=>$('integration-upload').click();landing.append(upload);$('chat').replaceChildren(landing);
  }
  $('integration-upload').onchange=async()=>{
    const file=$('integration-upload').files[0];if(!file)return;$('integration-upload').value='';
    if(file.size>2000000){$('connection-error').textContent='ZIP exceeds the 2 MB upload limit';return;}
    $('connection-error').textContent='Importing integration…';
    try{const response=await fetch('api/integrations/import',{method:'POST',headers:{'Content-Type':'application/zip'},body:file});
      const result=await response.json();if(!response.ok)throw new Error(result.detail || 'Import failed');
      await refresh();openIntegration(result.domain);$('connection-error').textContent='Imported into staging. Ask the agent to review and install it.';
    }catch(error){$('connection-error').textContent=error.message;}
  };
  $('new').onclick=()=>{if(state.activeJob && !state.integration){$('message').focus();return;}if(state.activeSummary && !state.conversations.some(conv=>conv.id===state.activeSummary.conversation_id)){openConversation(state.activeSummary.conversation_id,null);return;}state.integration=null;state.messageCount=0;updateComposer(null);state.selection++;state.conversation=null;state.context=null;state.domains=[];state.activeJob=null;state.chatKey='';remember();$('chat-title').textContent=t('newIntegration');newLanding();$('pending').replaceChildren();$('message').value='';resizeComposer();nav();showPanel(false);integrationDetails();document.body.classList.remove('menu-open');$('message').focus();};

  $('menu').onclick=()=>document.body.classList.toggle('menu-open');$('show-details').onclick=()=>{showPanel(true);integrationDetails();};

  $('close-integrations').onclick=()=>showPanel(false);

  window.addEventListener('keydown',event=>{if(event.key==='Escape'){event.preventDefault();event.stopImmediatePropagation();window.parent.postMessage({type:'ci-close-chat'},location.origin);}},{capture:true});

  $('toggle-panel').onclick=()=>{showPanel($('integration-panel').hidden || !document.body.classList.contains('details-open'));if(!$('integration-panel').hidden)integrationDetails();};

  let lastSubmission=null;

  function submission(text){if(!lastSubmission || lastSubmission.text!==text)lastSubmission={text,id:globalThis.crypto?.randomUUID?.() || `message-${Date.now()}-${Math.random().toString(36).slice(2)}`};return lastSubmission.id;}

  $('message').addEventListener('input',()=>{resizeComposer();updateComposer();});

  $('message').addEventListener('keydown',event=>{if(event.key!=='Enter' || event.isComposing)return;if(event.ctrlKey || event.shiftKey){event.preventDefault();const input=$('message');input.setRangeText('\n',input.selectionStart,input.selectionEnd,'end');input.dispatchEvent(new Event('input',{bubbles:true}));}else if(!event.altKey && !event.metaKey){event.preventDefault();if(!$('send').disabled)$('composer').requestSubmit();}});

  if(window.ResizeObserver)new ResizeObserver(resizeComposer).observe($('composer'));

  $('stop').onclick=async()=>{if(!state.activeJob)return;state.stopSending=true;updateComposer();try{await request(`api/jobs/${state.activeJob}/stop`,{});await refresh();}catch(error){$('connection-error').textContent=error.message;}finally{state.stopSending=false;updateComposer();}};

  function syncTheme(){

    const context=haHost();if(!context)return;

    try {

      const css=context.window.getComputedStyle(context.host);

      for(const key of ['primary-color','primary-text-color','secondary-text-color','primary-background-color','secondary-background-color','card-background-color','divider-color','error-color','success-color','primary-font-family','ha-font-family-body','ha-font-size-m','input-fill-color','input-ink-color','input-label-ink-color']){

        const value=css.getPropertyValue('--'+key);if(value.trim())document.documentElement.style.setProperty('--'+key,value);

      }

      const font=css.getPropertyValue('--ha-font-family-body').trim() || css.getPropertyValue('--primary-font-family').trim() || css.fontFamily;

      if(font && !/(Times New Roman|^serif$)/i.test(font))document.documentElement.style.setProperty('--primary-font-family',font);

      for(const face of context.window.document.fonts)if(!document.fonts.has(face))document.fonts.add(face);

    }catch(_){}

  }

  if(!new URLSearchParams(location.search).get('domain'))document.querySelector('.chat-header').hidden=true;
  newLanding();
  showPanel(window.innerWidth>700);resizeComposer();updateComposer();syncTheme();setInterval(syncTheme,3000);

  await refresh();

  const requestedDomain=new URLSearchParams(location.search).get('domain');
  if(requestedDomain && state.integrations.some(i=>i.domain===requestedDomain))openIntegration(requestedDomain);
  if(!requestedDomain && state.activeSummary?.conversation_id)await openConversation(state.activeSummary.conversation_id,null);
  updateConversationPicker();
  requestAnimationFrame(()=>$('message').focus({preventScroll:true}));

  async function poll(){if(!document.hidden)await refresh();setTimeout(poll,state.activeJob?1500:5000);}setTimeout(poll,1500);

})();

