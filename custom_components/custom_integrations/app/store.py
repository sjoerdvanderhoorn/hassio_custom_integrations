"""Thread-safe state persistence; never stores the API or Supervisor token."""
from __future__ import annotations

import json
import os
import threading
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, base: Path):
        self.path = base / "state.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.closed = False
        try:
            self.data = json.loads(self.path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            self.data = {"conversations": {}, "audit": []}
        except json.JSONDecodeError as exc:
            raise RuntimeError('Saved app state is invalid. Restore state.json from a backup before starting the app.') from exc
        # Translate only the old system default; preserve user titles and chat history.
        for conversation in self.data['conversations'].values():
            if conversation.get('title') == 'Nieuwe integratie':
                conversation['title'] = 'New integration'
            conversation.setdefault('domains', [])
        self.data.setdefault('jobs', {})
        self.data.setdefault('installations', {})
        self.data.setdefault('controls', {})
        self.data.setdefault('removals', {})
        self.data.setdefault('discoveries', {})
        self.data.setdefault('recoveries', {})
        # Old installation cards lacked a timeline anchor. Infer it once, never move on refresh.
        for item in self.data['installations'].values():
            if 'after_message' not in item:
                messages=self.data['conversations'].get(item.get('conversation_id'),{}).get('messages',[])
                anchors=[index+1 for index,msg in enumerate(messages) if msg.get('at','')<=item.get('created','')]
                item['after_message']=max(anchors,default=min(1,len(messages)))

    def save(self):
        with self.lock:
            if self.closed: return
            tmp = self.path.with_suffix(".tmp")
            with tmp.open('w', encoding='utf-8') as handle:
                json.dump(self.data, handle, indent=2, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)

    def new_conversation(self, domain: str | None = None) -> dict:
        with self.lock:
            ident = str(uuid.uuid4())
            conversation = {"id": ident, "title": "New integration", "session_id": None, "messages": [], "domains": [domain] if domain else [], "updated": now()}
            self.data["conversations"][ident] = conversation
            self.save()
            return deepcopy(conversation)

    def get_conversation(self, ident: str) -> dict | None:
        with self.lock:
            conversation = self.data["conversations"].get(ident)
            return deepcopy(conversation) if conversation else None

    def confirm_custom_build(self,ident):
        with self.lock:
            record=self.data['discoveries'].get(ident)
            if not record or not record.get('matches'): raise ValueError('No existing-integration choice is pending')
            record['custom_approved']=True;self.save()

    def set_session(self, ident: str, session_id: str):
        with self.lock:
            self.data["conversations"][ident]["session_id"] = session_id
            self.data["conversations"][ident]['session_revision'] = 10
            self.save()

    def add_message(self, ident: str, role: str, content: str, *, extra: dict | None = None):
        with self.lock:
            conv = self.data["conversations"][ident]
            if role == "user" and conv["title"] == "New integration":
                conv["title"] = content[:55]
            conv["messages"].append({"role": role, "content": content[:30000], "at": now(), **(extra or {})})
            conv["updated"] = now()
            self.save()

    def list_conversations(self):
        with self.lock:
            return [dict(id=c["id"], title=c["title"], updated=c["updated"], domains=c.get('domains', [])) for c in sorted(self.data["conversations"].values(), key=lambda x: x["updated"], reverse=True)]

    def link_domain(self, ident: str, domain: str):
        with self.lock:
            conv = self.data['conversations'][ident]
            if domain not in conv.setdefault('domains', []):
                conv['domains'].append(domain)
                self.save()

    def put(self, collection: str, ident: str, value: dict):
        with self.lock:
            self.data[collection][ident] = deepcopy(value)
            self.save()

    def records(self, collection: str):
        with self.lock:
            return deepcopy(self.data[collection])

    def audit(self, name: str, details: dict):
        with self.lock:
            self.data["audit"].append({"at": now(), "action": name, "details": details})
            self.data["audit"] = self.data["audit"][-500:]
            self.save()
