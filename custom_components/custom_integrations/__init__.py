"""Config entry setup, authenticated API bridge and frontend registration."""
from __future__ import annotations
from pathlib import Path
import asyncio
import httpx
from aiohttp import web
from homeassistant.components import frontend
from homeassistant.components.http import HomeAssistantView, StaticPathConfig
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from .const import DOMAIN, VERSION, FRONTEND_URL, API_URL

async def async_setup_entry(hass,entry):
    from .native import NativeHA
    from .app.main import create_app
    native=NativeHA(hass)
    options={**entry.data,**entry.options}
    data=Path(hass.config.path('.storage',DOMAIN))
    app=await hass.async_add_executor_job(lambda:create_app(data,Path(hass.config.config_dir),options,ha_client=native))
    native.manager=app.state.manager
    def built_in_domains():
        import homeassistant.components as components
        return {path.name for root in components.__path__ for path in Path(root).iterdir() if path.is_dir() and not path.name.startswith('_')}
    app.state.manager.blocked_domains=await hass.async_add_executor_job(built_in_domains)
    runtime={'requests':set(),'app':app,'native':native,'entry':entry,'client':httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://custom-integrations')}
    hass.data[DOMAIN]=runtime
    if not hass.data.get(DOMAIN+'_registered'):
        await hass.http.async_register_static_paths([StaticPathConfig(FRONTEND_URL,str(Path(__file__).parent/'frontend'),False)])
        hass.http.register_view(EngineView(hass))
        hass.data[DOMAIN+'_registered']=True
    module=FRONTEND_URL+'/extension.js?v='+VERSION
    frontend.add_extra_js_url(hass,module)
    runtime['module']=module
    app.state.installations.start()
    async def stop(_event=None):
        if runtime.get('stopped'):return
        runtime['stopped']=True
        native.closed=True
        app.state.installations.stop()
        def stop_jobs():
            for job in list(app.state.jobs.jobs.values()):
                if job['status'] in {'working','approval_required','stopping','stop_unconfirmed'}:
                    app.state.jobs.request_stop(job['id'])
                    app.state.jobs.status(job['id'],'interrupted')
        await hass.async_add_executor_job(stop_jobs)
        # Drain already accepted HTTP file operations before a replacement runtime starts.
        pending=[task for task in runtime['requests'] if task is not asyncio.current_task()]
        if pending:await asyncio.gather(*pending,return_exceptions=True)
        def quiesce():
            stop_jobs()
            with app.state.agent.action_lock, app.state.installations.lock:
                with app.state.store.lock:
                    app.state.store.closed=True
            # Best-effort cloud cancellation; local actions are already blocked.
            for remote in list(app.state.agent.runtimes.values()):
                try:remote['client'].beta.agents.sessions.events.create(remote['session'],events=[{'type':'agent.session.input.cancel'}],timeout=5)
                except Exception:pass
        await hass.async_add_executor_job(quiesce)
        await runtime['client'].aclose()
    runtime['stop']=stop
    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP,stop))
    entry.async_on_unload(entry.add_update_listener(_async_update_options))
    return True

async def _async_update_options(hass,entry):
    await hass.config_entries.async_reload(entry.entry_id)

async def async_unload_entry(hass,entry):
    runtime=hass.data.get(DOMAIN)
    if runtime:
        await runtime['stop']()
        frontend.remove_extra_js_url(hass,runtime['module'])
        hass.data.pop(DOMAIN,None)
    return True

class EngineView(HomeAssistantView):
    url=API_URL+'/{tail:.*}'
    name='api:custom_integrations:engine'
    requires_auth=True

    def __init__(self,hass):self.hass=hass

    async def _handle(self,request,tail):
        user=request.get('hass_user')
        if user is None or not user.is_admin:raise web.HTTPForbidden(reason='Administrator access is required')
        runtime=self.hass.data.get(DOMAIN)
        if not runtime or runtime.get('stopped'):raise web.HTTPServiceUnavailable(reason='Custom Integrations is not loaded')
        # Public assets use the static route. This is not an arbitrary HTTP proxy.
        if not tail.startswith('api/') or '..' in tail or '\\' in tail:raise web.HTTPNotFound()
        chunks=bytearray()
        async for chunk in request.content.iter_chunked(65536):
            if len(chunks)+len(chunk)>2_000_000:raise web.HTTPRequestEntityTooLarge(max_size=2_000_000,actual_size=len(chunks)+len(chunk))
            chunks.extend(chunk)
        if runtime.get('stopped'):raise web.HTTPServiceUnavailable(reason='Custom Integrations is stopping')
        task=asyncio.current_task();runtime.setdefault('requests',set()).add(task)
        try:
            response=await runtime['client'].request(request.method,'/'+tail,content=bytes(chunks),headers={'Content-Type':request.headers.get('Content-Type','application/json')})
        finally:runtime['requests'].discard(task)
        headers={key:value for key,value in response.headers.items() if key.lower() in {'content-type','content-disposition','cache-control','x-content-type-options'}}
        return web.Response(body=response.content,status=response.status_code,headers=headers)

    async def get(self,request,tail):return await self._handle(request,tail)
    async def post(self,request,tail):return await self._handle(request,tail)
