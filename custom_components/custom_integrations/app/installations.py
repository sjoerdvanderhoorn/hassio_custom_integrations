"""Durable install continuation; never replay deploys, restarts or ambiguous config submissions."""
from __future__ import annotations
import threading
import time
import uuid
from .store import now
from .ha import redact
from .integrations import validate_domain, IntegrationError, MARKER
from .action_logging import logger

ACTIVE = {'prepared','deploying','awaiting_restart','restart_requested','waiting_core','configuring','submitting','reconciling','verifying','needs_input','manual_setup','handing_over','paused'}


def configuration_values(values):
    import re
    if not isinstance(values, dict) or len(values) > 20:
        raise ValueError('Provide at most 20 non-secret configuration fields')
    for key, value in values.items():
        if not isinstance(key, str) or re.search(r'password|token|secret|key|auth|credential', key, re.I):
            raise ValueError('Enter credentials only in the official Home Assistant setup screen')
        if not isinstance(value, (str, int, float, bool, type(None))) or len(str(value)) > 1000:
            raise ValueError('Configuration fields must be short scalar values')
    return dict(values)


class Installations:
    def __init__(self, store, manager, ha):
        self.store, self.manager, self.ha = store, manager, ha
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.worker = None
        for item in self.list():
            if item['phase'] == 'deploying':
                self.update(item, 'interrupted', 'Installation was interrupted. Review the installed code before trying again.')
            elif item['phase'] in {'configuring','submitting','handing_over'}:
                self.update(item, 'reconciling', 'Checking whether interrupted configuration finished; input will not be replayed.')
            elif item['phase'] == 'restart_requested':
                self.update(item, 'reconciling', 'Restart request was interrupted. Checking configuration without requesting another restart.')

    def list(self):
        return list(self.store.records('installations').values())

    def get(self, ident):
        item = self.store.records('installations').get(ident)
        if item is None:
            raise ValueError('Installation not found')
        return item

    def update(self, item, phase, message, **fields):
        item.update(fields, phase=phase, message=message, updated=now())
        history=item.setdefault('history', [])
        if not history or history[-1]['phase']!=phase or history[-1]['message']!=message:
            history.append({'phase':phase,'message':message,'at':now()})
            logger.info('Installation phase | domain=%s | phase=%s',item['domain'],phase)
        self.store.put('installations', item['id'], item)
        return item

    def pause_requested(self, conversation):
        return bool(self.store.records('controls').get(conversation,{}).get('pause_installations'))

    def pause_item(self, item):
        phase=item['phase'] if item['phase'] in {'awaiting_restart','waiting_core','verifying','needs_input','manual_setup','reconciling'} else 'needs_input'
        return self.update(item,'paused','Paused because you stopped the agent. Completed actions have not been undone.',resume_phase=phase)

    def prepare(self, domain, values, conversation):
        validate_domain(domain)
        values = configuration_values(values)
        with self.lock:
            for item in self.list():
                if item['domain'] == domain and item['phase'] in ACTIVE:
                    return item
            item = {'id':uuid.uuid4().hex,'domain':domain,'conversation_id':conversation,'values':values,
                    'created':now(),'history':[],'flow_id':None,'not_before':0,'attempts':0,
                    'after_message':len(self.store.get_conversation(conversation)['messages'])}
            self.store.link_domain(conversation, domain)
            self.store.put('controls',conversation,{'pause_installations':False})
            return self.update(item, 'prepared', 'Configuration collected; ready to install.')

    def deploy(self, ident):
        with self.lock:
            item = self.get(ident)
            if item['phase'] != 'prepared':
                return item
            self.update(item, 'deploying', 'Installing validated integration code.')
            try:
                result = self.manager.deploy(item['domain'])
                return self.update(item, 'awaiting_restart', 'Code installed. Approve one Core restart to continue configuration.', deployment=result)
            except Exception as exc:
                self.update(item, 'interrupted', 'Installation failed; review the deployment before retrying.', error=redact(str(exc))[:500])
                raise

    def restart(self, ident):
        with self.lock:
            item = self.get(ident)
            if item['phase'] != 'awaiting_restart':
                raise ValueError('This installation is not waiting for restart approval')
            self.update(item, 'restart_requested', 'Requesting the approved Home Assistant restart.')
            try:
                self.ha.restart_core()
            except Exception as exc:
                return self.update(item, 'interrupted', 'Restart outcome is uncertain. Check Home Assistant before continuing.', error=redact(str(exc))[:500])
            return self.update(item, 'waiting_core', 'Waiting for Home Assistant; configuration will continue automatically.',
                               not_before=time.time()+10, deadline=time.time()+300)

    def continue_after_manual_restart(self, ident):
        """Explicit user action, never another restart or deployment."""
        with self.lock:
            item = self.get(ident)
            if item['phase']=='paused':
                self.store.put('controls',item['conversation_id'],{'pause_installations':False})
                return self.update(item,item.get('resume_phase','needs_input'),'Installation resumed after your confirmation.',not_before=0)
            if item['phase'] not in {'awaiting_restart','interrupted','needs_input'}:
                raise ValueError('This installation cannot be continued manually in its current state')
            if not (self.manager.installed_path(item['domain']) / MARKER).is_file():
                raise ValueError('Managed integration code is not installed')
            return self.update(item, 'waiting_core', 'Checking Home Assistant after your confirmation.',
                               not_before=0, deadline=time.time()+300, attempts=0)

    def pause_conversation(self, conversation):
        # Persist the request immediately, even when a Core HTTP call holds the worker lock.
        self.store.put('controls',conversation,{'pause_installations':True})
        if not self.lock.acquire(blocking=False): return
        try:
            for item in self.list():
                if item['conversation_id']==conversation and item['phase'] in {'awaiting_restart','waiting_core','verifying','needs_input','manual_setup','reconciling'}:
                    self.pause_item(item)
        finally:
            self.lock.release()

    def handoff(self, ident):
        """Explicitly release the saved flow before opening HA's native setup dialog."""
        with self.lock:
            item=self.get(ident)
            if item['phase'] not in {'needs_input','interrupted','manual_setup'}:
                raise ValueError('This installation does not need interactive setup')
            if not (self.manager.installed_path(item['domain']) / MARKER).is_file():
                raise ValueError('Managed integration code is not installed')
            entries=self.ha.entries(item['domain'])
            if entries:
                self.update(item,'verifying','Checking configuration completed in Home Assistant.',attempts=0)
                return {'path':'/config/integrations/integration/'+item['domain']}
            if item.get('flow_id'):
                self.update(item,'handing_over','Handing the current setup to the official Home Assistant dialog.')
                import httpx
                try:
                    self.ha.core('DELETE','/config/config_entries/flow/'+item['flow_id'])
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code != 404:
                        self.update(item,'needs_input','Could not hand setup to Home Assistant. No new flow was started.')
                        raise ValueError('Could not release the saved setup flow') from exc
                except Exception as exc:
                    self.update(item,'needs_input','Setup handoff was interrupted. Check Home Assistant before continuing.')
                    raise ValueError('The setup handoff outcome is uncertain; check Home Assistant') from exc
            # Recheck after cancelling: a concurrent OAuth completion may have created an entry.
            entries=self.ha.entries(item['domain'])
            self.update(item,'verifying' if entries else 'manual_setup',
                        'Finish the preselected integration in Home Assistant. This app will verify it automatically.',flow_id=None,attempts=0)
            return {'path':'/config/integrations/integration/'+item['domain'] if entries else '/config/integrations/add?domain='+item['domain']}

    def _configure(self, item):
        domain = item['domain']
        if self.pause_requested(item['conversation_id']):return self.pause_item(item)
        if item.get('flow_id'):
            # Saved flow IDs are read, never recreate an unknown or lost flow automatically.
            result = self.ha.core('GET', '/config/config_entries/flow/' + item['flow_id'])
        else:
            self.update(item, 'configuring', 'Starting the Home Assistant configuration flow.')
            result = self.ha.core('POST', '/config/config_entries/flow', json={'handler':domain})
        visited = set()
        for _ in range(5):
            kind = result.get('type')
            flow_id = result.get('flow_id') or item.get('flow_id')
            step = result.get('step_id')
            self.update(item, 'configuring', 'Reading the next configuration step.', flow_id=flow_id,
                        step_id=step, flow_type=kind)
            if self.pause_requested(item['conversation_id']):return self.pause_item(item)
            if kind == 'create_entry':
                return self.update(item, 'verifying', 'Configuration created; waiting for entities.', attempts=0)
            if kind == 'abort':
                return self.update(item, 'needs_input', 'Home Assistant stopped the configuration. Review it in Home Assistant.',
                                   reason=result.get('reason'))
            if kind != 'form' or result.get('errors') or step in visited:
                break
            visited.add(step)
            names = {field.get('name') for field in result.get('data_schema', []) if isinstance(field,dict)}
            values = {key:value for key,value in item['values'].items() if key in names}
            if not values:
                break
            self.update(item, 'submitting', 'Applying the collected non-secret configuration.', flow_id=flow_id)
            # HA accepts the input object directly, not a user_input wrapper.
            result = self.ha.core('POST', '/config/config_entries/flow/'+flow_id, json=values)
        return self.update(item, 'needs_input', 'Additional setup is needed. Open Home Assistant below to finish pairing, credentials or the current form.',
                           flow_id=result.get('flow_id') or item.get('flow_id'), step_id=result.get('step_id'),
                           flow_type=result.get('type'), errors=result.get('errors', {}))

    def advance(self, ident):
        with self.lock:
            item = self.get(ident)
            if self.pause_requested(item['conversation_id']) and item['phase'] in {'awaiting_restart','waiting_core','verifying','needs_input','manual_setup','reconciling'}:
                return self.pause_item(item)
            if item['phase'] not in {'waiting_core','verifying','needs_input','reconciling','manual_setup'} or time.time() < item.get('not_before',0):
                return item
            try:
                self.ha.check()
                entries = self.ha.entries(item['domain'])
                if entries:
                    # Reconciliation is read-only: any existing domain entry prevents duplicate setup.
                    entities = self.ha.entity_states(item['domain'], entries=entries)['entities']
                    if any(e.get('state') == 'loaded' and not e.get('disabled_by') for e in entries) and any(
                        entity.get('state') not in {None,'unknown','unavailable'} for entity in entities):
                        return self.update(item, 'complete', 'Integration configured. Entities and their reported states were inspected.',
                                           entries=entries, entities=entities, values={})
                    attempts=item.get('attempts',0)+1
                    if attempts >= 24:
                        return self.update(item, 'needs_input', 'Configuration exists, but setup or entities need attention in Home Assistant.',
                                           entries=entries, entities=entities, attempts=attempts, not_before=time.time()+15)
                    return self.update(item, 'verifying', 'Configuration exists; waiting for setup and registered entities.',
                                       entries=entries, entities=entities, attempts=attempts)
                if item['phase'] == 'waiting_core':
                    return self._configure(item)
                if item['phase'] == 'reconciling':
                    return self.update(item, 'needs_input', 'An action was interrupted. Check the saved flow in Home Assistant; it has not been resubmitted.')
                if item['phase'] == 'verifying':
                    attempts=item.get('attempts',0)+1
                    return self.update(item, 'needs_input' if attempts>=24 else 'verifying',
                                       'Waiting for the created config entry. Check Home Assistant if it does not appear.', attempts=attempts)
                return item
            except Exception as exc:
                # Ambiguous mutations must not be retried. Only connectivity reads may retry.
                if item['phase'] in {'configuring','submitting'}:
                    return self.update(item, 'needs_input', 'Configuration outcome is uncertain. Check Home Assistant before continuing.', error=redact(str(exc))[:500])
                if time.time() > item.get('deadline',time.time()+1) and item['phase']=='waiting_core':
                    return self.update(item, 'needs_input', 'Home Assistant did not return in time. Check its status, then continue.', error=redact(str(exc))[:500])
                item['last_error']=redact(str(exc))[:500]
                self.store.put('installations',item['id'],item)
                return item

    def start(self):
        def run():
            while not self.stop_event.is_set():
                for item in self.list():
                    if self.stop_event.is_set(): break
                    self.advance(item['id'])
                self.stop_event.wait(5)
        self.worker=threading.Thread(target=run, daemon=True)
        self.worker.start()

    def stop(self):
        self.stop_event.set()
