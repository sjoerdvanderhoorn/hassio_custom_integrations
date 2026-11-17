"""Synchronous worker adapter to Home Assistant's event-loop APIs; no Supervisor token."""
from __future__ import annotations
import asyncio
import json
from homeassistant import const as ha_const
from .app.ha import HAClient, redact
from .app.integrations import validate_domain, MARKER

class NativeHA(HAClient):
    def __init__(self,hass):
        self.hass=hass
        self.token=''
        self.closed=False
        self.manager=None

    def submit(self,awaitable):
        if self.closed:
            awaitable.close()
            raise RuntimeError('Custom Integrations is stopping; no new HA action was started')
        future=asyncio.run_coroutine_threadsafe(awaitable,self.hass.loop)
        try:return future.result(timeout=45)
        except TimeoutError as exc:
            # A mutation may already have reached HA. Never retry it automatically.
            future.cancel()
            raise RuntimeError('Home Assistant action timed out; outcome may be uncertain. Inspect before retrying.') from exc

    def owned(self,domain):
        validate_domain(domain)
        if not self.manager: raise ValueError('Integration manager unavailable')
        if not self.manager.workspace(domain).exists() and not (self.manager.installed_path(domain)/MARKER).is_file():
            raise ValueError('Only managed integrations are accessible')

    def check(self):
        async def run():
            if self.hass.is_stopping:raise RuntimeError('Home Assistant is stopping')
            return {'connected':True,'version':getattr(ha_const,'__version__','unknown'),'location_name':self.hass.config.location_name}
        return self.submit(run())

    def entries(self,domain):
        self.owned(domain)
        async def run():
            return [{'entry_id':e.entry_id,'domain':e.domain,'title':e.title,'state':getattr(e.state,'value',str(e.state)),
                     'disabled_by':getattr(e.disabled_by,'value',e.disabled_by)} for e in self.hass.config_entries.async_entries(domain)]
        return self.submit(run())

    def entity_states(self,domain,entries=None):
        self.owned(domain)
        async def run():
            from homeassistant.helpers import entity_registry as er
            ids={e.entry_id for e in self.hass.config_entries.async_entries(domain)}
            entities=[]
            for item in er.async_get(self.hass).entities.values():
                if item.config_entry_id not in ids and item.platform!=domain:continue
                state=self.hass.states.get(item.entity_id)
                attrs=state.attributes if state else {}
                entities.append({'entity_id':item.entity_id,'state':state.state if state else None,'name':item.name,
                    'original_name':item.original_name,'config_entry_id':item.config_entry_id,
                    'disabled_by':getattr(item.disabled_by,'value',item.disabled_by),
                    'attributes':{k:v for k,v in attrs.items() if k in {'friendly_name','unit_of_measurement','brightness','supported_color_modes','color_mode','device_class','icon','supported_features'}},
                    'last_updated':state.last_updated.isoformat() if state else None})
            return {'domain':domain,'entities':entities}
        return self.submit(run())

    def logs(self,domain,limit=100):
        self.owned(domain)
        async def run():
            handler=self.hass.data.get('system_log')
            if not handler:raise RuntimeError('Home Assistant system_log is not loaded')
            records=handler.records.to_list()
            prefix='custom_components.'+domain
            matches=[record for record in records if (str(record.get('name',''))==prefix or str(record.get('name','')).startswith(prefix+'.')) or f'custom_components/{domain}/' in str(record.get('source',''))]
            selected=matches[:max(5,min(int(limit),200))]
            return {'domain':domain,'logs':redact('\n'.join(json.dumps(r,default=str) for r in selected))[:18000],
                    'matching_lines':len(selected),'source':'Home Assistant system_log warning/error buffer; not the full raw log'}
        return self.submit(run())

    def wait_for_core(self,timeout=120):
        return {"online":not self.closed,"restart_observed":False,"note":"A Core integration cannot observe its own restart from the same process. Installation progress is persisted and checked after startup."}

    def activity(self,domain,entities):
        return {'available':False,'events':[],'truncated':False}

    def core(self,method,path,**kwargs):
        async def run():
            from homeassistant import config_entries
            body=kwargs.get('json',{})
            prefix='/config/config_entries/'
            if path.startswith(prefix+'entry/'):
                parts=path[len(prefix+'entry/'):].split('/')
                entry=self.hass.config_entries.async_get_entry(parts[0])
                if not entry:raise ValueError('Configuration entry no longer exists')
                await self.hass.async_add_executor_job(self.owned,entry.domain)
                if method=='DELETE' and len(parts)==1:
                    # Keep HA removal alive if the worker's wait is interrupted.
                    task=self.hass.async_create_task(self.hass.config_entries.async_remove(entry.entry_id),'Custom Integrations entry removal')
                    return await asyncio.shield(task)
                if method=='POST' and parts[1:]==['reload']:
                    return await self.hass.config_entries.async_reload(entry.entry_id)
            if path==prefix+'flow' and method=='POST':
                domain=body['handler'];await self.hass.async_add_executor_job(self.owned,domain)
                result=await self.hass.config_entries.flow.async_init(domain,context={'source':config_entries.SOURCE_USER})
                return self.flow_result(result)
            if path.startswith(prefix+'flow/'):
                ident=path[len(prefix+'flow/'):]
                if '/' in ident:raise ValueError('Invalid flow ID')
                from homeassistant.data_entry_flow import UnknownFlow
                try:flow=self.hass.config_entries.flow.async_get(ident)
                except UnknownFlow:
                    if method=='DELETE':return {'aborted':True,'already_missing':True}
                    raise ValueError('Saved setup flow no longer exists. Use Continue setup in Home Assistant.')
                await self.hass.async_add_executor_job(self.owned,flow['handler'])
                if method=='DELETE':
                    self.hass.config_entries.flow.async_abort(ident);return {'aborted':True}
                result=await self.hass.config_entries.flow.async_configure(ident,body if method=='POST' else None)
                return self.flow_result(result)
            if path.startswith('/states/') and method=='GET':
                state=self.hass.states.get(path[len('/states/'):])
                if not state:raise ValueError('Entity not found')
                return state.as_dict()
            if path.startswith('/services/') and method=='POST':
                domain,service=path[len('/services/'):].split('/')
                if (domain,service) not in {('homeassistant','restart'),('light','turn_on'),('light','turn_off'),('switch','turn_on'),('switch','turn_off')}:
                    raise ValueError('Unsupported service action')
                await self.hass.services.async_call(domain,service,body,blocking=domain!='homeassistant')
                return []
            raise ValueError('Unsupported native Home Assistant operation')
        return self.submit(run())

    @staticmethod
    def flow_result(result):
        output={k:v for k,v in result.items() if k in {'type','flow_id','handler','step_id','errors','reason'}}
        output['type']=getattr(result['type'],'value',result['type'])
        if result.get('data_schema') is not None:
            schema=getattr(result['data_schema'],'schema',{})
            output['data_schema']=[{'name':str(getattr(key,'schema',key))} for key in schema]
        # No config data, proposed values, credentials or entry objects leave Core.
        return output
