/* Only API requests use the signed-in administrator's HA authentication. No token in URLs/storage. */
(() => {
  const fetchNative=window.fetch.bind(window);
  window.fetch=(input,options={})=>{
    const url=new URL(typeof input==='string'?input:input.url,location.href);
    const relative=url.pathname.split('/chat/')[1];
    if(relative?.startsWith('api/')){
      const host=window.parent.document.querySelector('home-assistant');
      if(!host?.hass?.user?.is_admin)return Promise.reject(new Error('Administrator access is required'));
      return host.hass.fetchWithAuth('/api/custom_integrations/engine/'+relative,options);
    }
    if(url.origin!==location.origin)return Promise.reject(new Error('Unexpected cross-origin request'));
    return fetchNative(input,options);
  };
})();
