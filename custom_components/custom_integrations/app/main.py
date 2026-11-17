"""Internal dashboard and chat API for Custom Integrations."""
from __future__ import annotations

import json
import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .agent import AgentBridge, Jobs
from .ha import HAClient, redact, SUPERVISOR
from .integrations import IntegrationError, IntegrationManager, validate_domain
from .store import Store
from .installations import Installations
from .markdown import render_markdown
from .transfers import Transfers, MAX_ARCHIVE

HERE = Path(__file__).resolve().parent


def load_options() -> dict:
    options_file = Path(os.getenv("HA_OPTIONS_PATH", "/data/options.json"))
    try:
        data = json.loads(options_file.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    return data


class MessageRequest(BaseModel):
    conversation_id: str | None = None
    message: str = Field(min_length=1, max_length=12000)
    domain: str | None = None
    submission_id: str = Field(default_factory=lambda: __import__('uuid').uuid4().hex, min_length=1, max_length=100)


class ApprovalRequest(BaseModel):
    request_id: str
    decision: Literal["approve", "deny"]


class InstallationAction(BaseModel):
    action: Literal['restart', 'continue', 'handoff']
    confirmed: bool = False


def create_app(data_dir: Path | None = None, ha_dir: Path | None = None, options: dict | None = None, ha_client=None):
    data_dir = data_dir or Path(os.getenv("HA_BUILDER_DATA", "/data"))
    ha_dir = ha_dir or Path(os.getenv("HA_CONFIG_DIR", "/ha_config"))
    options = options if options is not None else load_options()
    store = Store(data_dir)
    manager = IntegrationManager(data_dir, ha_dir)
    ha = ha_client if ha_client is not None else HAClient()
    jobs = Jobs(store)
    installations = Installations(store, manager, ha)
    transfers = Transfers(manager, store, ha, installations)
    agent = AgentBridge(store, manager, ha, jobs, options, installations)
    agent.transfers = transfers

    @asynccontextmanager
    async def lifespan(app):
        installations.start()
        yield
        installations.stop()

    app = FastAPI(title="Custom Integrations", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store, app.state.manager, app.state.jobs, app.state.agent = store, manager, jobs, agent
    app.state.installations = installations
    active_lock = threading.Lock()
    active = {"job": None}
    extras_cache = {}
    extras_lock = threading.Lock()

    @app.middleware("http")
    async def ingress_protection(request: Request, call_next):
        # The Supervisor ingress proxy is the only authorized HTTP client.
        if ha_client is None and os.getenv("HA_INGRESS_ONLY", "1") == "1" and (not request.client or request.client.host != "172.30.32.2"):
            return JSONResponse({"error": "Accessible only through Home Assistant Ingress"}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    app.mount("/static", StaticFiles(directory=str(HERE.parent / "frontend" / "chat" / "static")), name="static")

    @app.get("/")
    def index():
        return FileResponse(HERE.parent / "frontend" / "chat" / "index.html", media_type="text/html")

    def require_idle():
        if active['job'] and jobs.get(active['job']).get('status') in {'working','approval_required','stopping','stop_unconfirmed'}:
            raise HTTPException(409, 'Stop the agent before managing integration files')

    @app.post('/api/integrations/import')
    async def import_integration(request: Request):
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw)>MAX_ARCHIVE: raise HTTPException(413, 'ZIP exceeds the 2 MB upload limit')
        with active_lock:
            require_idle()
            try: return transfers.import_zip(bytes(raw))
            except (ValueError, OSError) as exc: raise HTTPException(400, redact(str(exc))) from exc

    @app.get('/api/integrations/{domain}/share')
    def share_integration(domain: str):
        with active_lock:
            require_idle()
            try: content=transfers.export_zip(domain)
            except (ValueError, OSError) as exc: raise HTTPException(400, redact(str(exc))) from exc
        return Response(content, media_type='application/zip', headers={'Content-Disposition':f'attachment; filename="{domain}.zip"'})

    @app.post('/api/integrations/{domain}/uninstall')
    def uninstall_integration(domain: str, body: dict):
        if body.get('confirmed') is not True: raise HTTPException(400, 'Explicit uninstall confirmation is required')
        with active_lock:
            require_idle()
            try: return transfers.uninstall(domain)
            except Exception as exc: raise HTTPException(400, redact(str(exc))[:1000]) from exc

    @app.get("/api/state")
    def state():
        try:
            ha_info = ha.check()
        except Exception as exc:
            ha_info = {"connected": False, "error": redact(str(exc))[:200]}
        items = [item for item in manager.list_domains() if named_integration(item['domain'])]
        for item in items:
            item.update(name=integration_name(item['domain']), icon=f"api/integrations/{item['domain']}/icon")
        visible={item['domain'] for item in items}
        running=jobs.get(active['job']) if active['job'] else None
        return {"conversations": [conv for conv in store.list_conversations() if visible.intersection(conv.get('domains',[]))], "integrations": items,
                "active_job": {k:running[k] for k in ('id','conversation_id','status')} if running and running['status'] in {'working','approval_required','stopping','stop_unconfirmed'} else None,
                "installations": [public_installation(item) for item in installations.list()],
                "ha": ha_info, "settings": {k: bool(options.get(k)) for k in ("auto_deploy", "auto_restart")},
                "api_key_configured": bool(options.get("openai_api_key") or os.getenv("OPENAI_API_KEY"))}

    @app.post("/api/conversations")
    def new_conversation():
        return store.new_conversation()

    @app.get("/api/conversations/{conversation_id}")
    def get_conversation(conversation_id: str):
        item = store.get_conversation(conversation_id)
        if item is None:
            raise HTTPException(404, "Conversation not found")
        for message in item['messages']:
            if message['role']=='assistant':
                message['rendered_content']=render_markdown(message['content'])
        return {**item, 'jobs': jobs.for_conversation(conversation_id),
                'installations': [public_installation(i) for i in installations.list() if i['conversation_id']==conversation_id]}

    def public_installation(item):
        return {k:v for k,v in item.items() if k not in {'values'}}

    def integration_name(domain):
        for base in (manager.workspace(domain), manager.installed_path(domain)):
            try:
                manifest=json.loads((base/'manifest.json').read_text(encoding='utf-8'))
                return manifest.get('name') or domain
            except (OSError, ValueError, AttributeError):
                pass
        return domain

    def named_integration(domain):
        for base in (manager.workspace(domain),manager.installed_path(domain)):
            try:
                manifest=json.loads((base/'manifest.json').read_text(encoding='utf-8'))
                if manifest.get('domain')==domain and isinstance(manifest.get('name'),str) and manifest['name'].strip():
                    return True
            except (OSError,ValueError,AttributeError):
                pass
        return False

    def require_managed(domain):
        try: validate_domain(domain)
        except IntegrationError as exc: raise HTTPException(400,str(exc)) from exc
        if not any(item['domain']==domain for item in manager.list_domains()):
            raise HTTPException(404,'Managed integration not found')

    def entity_names(domain, entities, entries=None):
        prefixes=sorted({integration_name(domain), *(entry.get('title','') for entry in entries or [])},key=len,reverse=True)
        for entity in entities:
            name=entity.get('name') or entity.get('original_name') or entity.get('attributes',{}).get('friendly_name') or entity['entity_id']
            for prefix in prefixes:
                if prefix and name.casefold().startswith(prefix.casefold()) and len(name)>len(prefix) and name[len(prefix)] in ' _-:–—':
                    suffix=name[len(prefix):].lstrip(' _-:–—')
                    if suffix: name=suffix;break
            entity['display_name']=name
        return entities

    @app.get('/api/integrations/{domain}/activity')
    def integration_activity(domain: str):
        require_managed(domain)
        with extras_lock:
            cached=extras_cache.get(domain)
            if cached and time.monotonic()-cached[0]<30:
                return cached[1]
        try:
            entities=ha.entity_states(domain)['entities']
            activity=ha.activity(domain,entities)
        except Exception:
            activity={'available':False,'events':[],'truncated':False}
        try:
            ha.logs(domain,limit=5)
            logs_available=True
        except Exception:
            logs_available=False
        data={**activity,'logs_available':logs_available}
        with extras_lock:
            extras_cache[domain]=(time.monotonic(),data)
        return data

    @app.get('/api/integrations/{domain}/logs')
    def integration_logs(domain: str):
        require_managed(domain)
        try: return ha.logs(domain,limit=200)
        except Exception as exc:
            raise HTTPException(503,'Integration logs are not available from Home Assistant') from exc

    @app.get('/api/integrations/{domain}/icon')
    def integration_icon(domain: str):
        try:
            validate_domain(domain)
            if not any(item['domain']==domain for item in manager.list_domains()):
                raise HTTPException(404, 'Managed integration not found')
            for base in (manager.installed_path(domain),manager.workspace(domain)):
                path=base/'brand'/'icon.png'
                if path.is_file() and not any(p.is_symlink() for p in (path,path.parent,base)) and path.stat().st_size <= 500_000:
                    content=path.read_bytes()
                    if content.startswith(b'\x89PNG\r\n\x1a\n'):
                        return Response(content,media_type='image/png')
            if ha.token:
                response=ha.client.get(SUPERVISOR+'/core/api/brands/integration/'+domain+'/icon.png',params={'placeholder':'no'})
                if response.status_code==200 and response.content.startswith(b'\x89PNG\r\n\x1a\n') and len(response.content)<=500_000:
                    return Response(response.content,media_type='image/png')
        except IntegrationError as exc:
            raise HTTPException(400,str(exc)) from exc
        except HTTPException:
            raise
        except Exception:
            pass
        return FileResponse(HERE.parent/'frontend/chat/static/integration.svg',media_type='image/svg+xml')

    @app.post('/api/installations/{ident}/action')
    def installation_action(ident: str, body: InstallationAction):
        if not body.confirmed:
            raise HTTPException(400,'Explicit confirmation is required')
        try:
            if body.action=='handoff':
                return installations.handoff(ident)
            item=installations.restart(ident) if body.action=='restart' else installations.continue_after_manual_restart(ident)
            return public_installation(item)
        except ValueError as exc:
            raise HTTPException(400,str(exc)) from exc

    @app.get("/api/integrations/{domain}")
    def integration(domain: str):
        try:
            validate_domain(domain)
            managed = next((item for item in manager.list_domains() if item['domain'] == domain), None)
            if managed is None:
                raise HTTPException(404, "Managed integration not found")
            name = integration_name(domain)
            validation = manager.validate(domain) if manager.workspace(domain).exists() else None
            errors = {}
            try:
                entries = ha.entries(domain)
            except Exception as exc:
                entries = None
                errors['entries'] = redact(str(exc))[:300]
            try:
                entities = entity_names(domain,ha.entity_states(domain, entries=entries)['entities'],entries) if entries is not None else None
            except Exception as exc:
                entities = None
                errors['entities'] = redact(str(exc))[:300]
            return {**managed, "name": name, "configured": bool(entries) if entries is not None else None,
                    "validation": validation, "entries": entries, "entities": entities, "errors": errors,
                    "backups": manager.backups_for(domain), "integration_path": f'/config/integrations/integration/{domain}',
                    "icon": f'api/integrations/{domain}/icon'}
        except IntegrationError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/chat")
    def chat(body: MessageRequest):
        with active_lock:
            # A lost HTTP response must not turn a retry into a second agent turn.
            conversations=([store.get_conversation(body.conversation_id)] if body.conversation_id else
                           [store.get_conversation(item['id']) for item in store.list_conversations()])
            for existing in filter(None,conversations):
                for index,message in enumerate(existing['messages']):
                    if message.get('submission_id')==body.submission_id:
                        if message['content']!=body.message:
                            raise HTTPException(409,'This submission ID was already used for a different message')
                        candidates=[job for job in jobs.for_conversation(existing['id']) if job['after_message']<=index+1]
                        if candidates:
                            prior=max(candidates,key=lambda job:job['after_message'])
                            return {'conversation_id':existing['id'],'job_id':prior['id'],'steered':bool(message.get('steering'))}
            if active["job"] and jobs.get(active["job"])["status"] in {"working", "approval_required", 'stopping', 'stop_unconfirmed'}:
                running=jobs.get(active['job'])
                if running['conversation_id']!=body.conversation_id:
                    raise HTTPException(409,'The agent is busy in another conversation. Open that conversation to steer or stop it.')
                conv=store.get_conversation(body.conversation_id)
                if any(msg.get('submission_id')==body.submission_id for msg in conv['messages']):
                    return {'conversation_id':conv['id'],'job_id':active['job'],'steered':True}
                try:
                    agent.steer(active['job'],body.message,body.submission_id)
                except ValueError as exc:
                    raise HTTPException(409,str(exc)) from exc
                except Exception as exc:
                    raise HTTPException(502,'Could not confirm delivery to the agent. Retry the same message.') from exc
                return {'conversation_id':conv['id'],'job_id':active['job'],'steered':True}
            conv = store.get_conversation(body.conversation_id) if body.conversation_id else None
            if body.conversation_id and not conv:
                raise HTTPException(404, "Conversation not found")
            if not conv:
                if body.domain:
                    try:
                        validate_domain(body.domain)
                    except IntegrationError as exc:
                        raise HTTPException(400,str(exc)) from exc
                    if not any(item['domain']==body.domain for item in manager.list_domains()):
                        raise HTTPException(404,'Managed integration not found')
                conv = store.new_conversation(body.domain)
            elif body.domain and body.domain not in conv.get('domains',[]):
                raise HTTPException(400,'Integration context does not match this conversation')
            store.add_message(conv["id"], "user", body.message, extra={'submission_id':body.submission_id})
            job_id = jobs.new(conv["id"])
            active["job"] = job_id
            worker = threading.Thread(target=agent.run, args=(conv["id"], body.message, job_id), daemon=True)
            worker.start()
        return {"conversation_id": conv["id"], "job_id": job_id}

    @app.get("/api/jobs/{job_id}")
    def job(job_id: str):
        data = jobs.get(job_id)
        if data is None:
            raise HTTPException(404, "Job not found")
        return data

    @app.post("/api/jobs/{job_id}/approve")
    def approval(job_id: str, body: ApprovalRequest):
        try:
            jobs.decide(job_id, body.request_id, body.decision)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"accepted": True}

    @app.post('/api/jobs/{job_id}/stop')
    def stop_job(job_id: str):
        with active_lock:
            if active['job']!=job_id:
                raise HTTPException(409,'This agent task is no longer active')
            try:
                agent.stop(job_id)
            except ValueError as exc:
                raise HTTPException(409,str(exc)) from exc
            except Exception as exc:
                jobs.status(job_id,'stop_unconfirmed')
                raise HTTPException(502,'Local actions are blocked, but remote cancellation could not be confirmed. Retry Stop.') from exc
        return {'accepted':True,'status':jobs.get(job_id)['status']}

    return app



