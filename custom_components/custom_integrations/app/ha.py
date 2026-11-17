"""Minimal, bounded access to Home Assistant Core and Supervisor APIs."""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import websocket

from .integrations import validate_domain

SUPERVISOR = os.getenv("SUPERVISOR_URL", "http://supervisor").rstrip("/")
WS_URL = os.getenv("HA_WS_URL", "ws://supervisor/core/websocket")


def redact(text: str) -> str:
    """Best-effort redaction. User must avoid exposing credentials in device logs."""
    text = re.sub(r"(?i)Bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [REDACTED]", text)
    text = re.sub(r"(?i)((?:api[_-]?key|access[_-]?token|client[_-]?secret|password|authorization)\s*[:=]\s*)[^\s,;}]+", r"\1[REDACTED]", text)
    text = re.sub(r"(?i)([?&](?:key|token|password|secret)=)[^&\s]+", r"\1[REDACTED]", text)
    return text


class HAClient:
    def __init__(self, token: str | None = None):
        self.token = token if token is not None else os.environ.get("SUPERVISOR_TOKEN", "")
        self.client = httpx.Client(timeout=18, headers={"Authorization": f"Bearer {self.token}"})

    def call(self, method: str, path: str, **kw):
        if not self.token:
            raise RuntimeError("SUPERVISOR_TOKEN is missing. Run this app inside Home Assistant.")
        response = self.client.request(method, SUPERVISOR + path, **kw)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        if "json" in content_type:
            return response.json()
        return response.text

    def core(self, method: str, path: str, **kw):
        if not path.startswith("/") or ".." in path:
            raise ValueError("Invalid API path")
        return self.call(method, "/core/api" + path, **kw)

    def websocket_command(self, command: dict):
        if not self.token:
            raise RuntimeError("SUPERVISOR_TOKEN is missing")
        ws = websocket.create_connection(WS_URL, timeout=12)
        try:
            if json.loads(ws.recv()).get("type") != "auth_required":
                raise RuntimeError("Unexpected Home Assistant WebSocket handshake")
            ws.send(json.dumps({"type": "auth", "access_token": self.token}))
            auth = json.loads(ws.recv())
            if auth.get("type") != "auth_ok":
                raise RuntimeError("Home Assistant WebSocket authentication failed")
            ws.send(json.dumps({"id": 1, **command}))
            while True:
                data = json.loads(ws.recv())
                if data.get("id") == 1:
                    if not data.get("success"):
                        raise RuntimeError(f"WebSocket error: {data.get('error')}")
                    return data.get("result")
        finally:
            ws.close()

    def check(self):
        info = self.core("GET", "/config")
        return {"connected": True, "version": info.get("version"), "location_name": info.get("location_name")}

    def entries(self, domain: str):
        validate_domain(domain)
        result = self.core("GET", "/config/config_entries/entry", params={"domain": domain})
        return [{k: item.get(k) for k in ("entry_id", "domain", "title", "state", "disabled_by") if k in item} for item in result]

    def entity_states(self, domain: str, entries: list | None = None):
        validate_domain(domain)
        entries = self.entries(domain) if entries is None else entries
        entry_ids = {e["entry_id"] for e in entries if "entry_id" in e}
        registry = self.websocket_command({"type": "config/entity_registry/list"})
        # Platform ownership also includes registered YAML entities without config entries.
        owned = {e['entity_id']: e for e in registry if e.get('config_entry_id') in entry_ids or e.get('platform') == domain}
        entity_ids = set(owned)
        all_states = self.core("GET", "/states")
        states = {s["entity_id"]: s for s in all_states if s["entity_id"] in entity_ids}
        entities = []
        for ident in sorted(entity_ids):
            state = states.get(ident)
            attrs = state.get("attributes", {}) if state else {}
            entities.append({"entity_id": ident, "state": state["state"] if state else None,
                             "name": owned[ident].get('name'), "original_name": owned[ident].get('original_name'),
                             "disabled_by": owned[ident].get('disabled_by'), "config_entry_id": owned[ident].get('config_entry_id'),
                             "last_updated": state.get('last_updated') if state else None,
                             "attributes": {k: attrs[k] for k in ("friendly_name", "brightness", "supported_color_modes", "color_mode", "supported_features", "unit_of_measurement", "percentage", "current_temperature") if k in attrs}})
        return {"domain": domain, "entries": entries, "entities": entities}

    def activity(self, domain: str, entities: list):
        """Use HA's actual Logbook data, never a synthetic list of current state changes."""
        validate_domain(domain)
        ids=sorted({entity['entity_id'] for entity in entities})
        if not ids:
            return {'available':True,'events':[],'truncated':False}
        now=datetime.now(timezone.utc)
        result=self.websocket_command({'type':'logbook/get_events', 'entity_ids':ids[:200],
                                       'start_time':(now-timedelta(hours=24)).isoformat(), 'end_time':now.isoformat()})
        if not isinstance(result,list):
            raise RuntimeError('Home Assistant returned an invalid Activity response')
        allowed=set(ids[:200])
        events=[{key:item[key] for key in ('when','name','entity_id','message','state','domain','context_domain','context_service') if key in item}
                for item in result if isinstance(item,dict) and (item.get('entity_id') in allowed or (not item.get('entity_id') and item.get('domain')==domain))]
        events.sort(key=lambda item:item.get('when',0),reverse=True)
        return {'available':True,'events':events[:50],'truncated':len(ids)>200 or len(events)>50}

    def single_state(self, entity_id: str):
        if not re.fullmatch(r"[a-z_]+\.[a-z0-9_]+", entity_id):
            raise ValueError("Invalid entity_id")
        state = self.core("GET", "/states/" + entity_id)
        attrs = state.get("attributes", {})
        return {"entity_id": entity_id, "state": state.get("state"), "attributes": {k: attrs[k] for k in ("friendly_name", "brightness", "supported_color_modes", "supported_features", "percentage") if k in attrs}}

    def logs(self, domain: str, limit: int = 100):
        validate_domain(domain)
        limit = max(5, min(int(limit), 200))
        # Reading only recent matching lines plus local context prevents unrelated logs
        # from being sent to the OpenAI service.
        try:
            raw = self.call("GET", "/core/logs")
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code==403:
                raise RuntimeError("Home Assistant denied Core log access. This app requires hassio_api: true and hassio_role: homeassistant. Update the app definition, refresh the local app store, rebuild/update the app and restart it so Supervisor applies the permission. Do not change the generated integration or disable authentication.") from exc
            if exc.response.status_code==401:
                raise RuntimeError('Supervisor authentication failed while reading Core logs. Restart the app and check its Supervisor configuration; never paste the Supervisor token into chat.') from exc
            raise
        if isinstance(raw, dict):
            raw = json.dumps(raw, ensure_ascii=False)
        lines = str(raw).splitlines()[-8000:]
        needles = (f"custom_components.{domain}", f"custom_components/{domain}", f"[{domain}]", f"homeassistant.components.{domain}")
        matching = set()
        for i, line in enumerate(lines):
            if any(n in line.lower() for n in needles):
                matching.update(range(max(0, i - 2), min(len(lines), i + 7)))
        selected = [lines[i] for i in sorted(matching)][-limit:]
        return {"domain": domain, "matching_lines": len(selected), "logs": redact("\n".join(selected))[-18000:]}

    def start_config_flow(self, domain: str, values: dict | None = None):
        validate_domain(domain)
        values = values or {}
        if not isinstance(values, dict) or len(values) > 20:
            raise ValueError("Invalid input")
        if any(re.search(r"(?i)(password|token|secret|key|auth)", k) for k in values):
            raise ValueError("Enter secrets in Home Assistant itself")
        if self.entries(domain):
            return {"already_registered": True, "entries": self.entries(domain)}
        result = self.core("POST", "/config/config_entries/flow", json={"handler": domain})
        if result.get("type") == "form" and values:
            result = self.core("POST", "/config/config_entries/flow/" + result["flow_id"], json=values)
        if result.get("type") == "form":
            # Schemas may contain proposed values including secrets: strip them.
            return {"type": "form", "step_id": result.get("step_id"), "needs_input": True, "message": "Open Settings > Devices & services > Add integration to complete setup, or supply non-secret fields in chat."}
        return {"type": result.get("type"), "registered": result.get("type") == "create_entry", "result": {k: v for k, v in result.get("result", {}).items() if k in {"entry_id", "domain", "title"}}}

    def reload_entry(self, domain: str):
        entries = self.entries(domain)
        if not entries:
            return {"reloaded": [], "message": "No config entry exists yet."}
        results = []
        for entry in entries:
            entry_id = entry["entry_id"]
            results.append({"entry_id": entry_id, "result": self.core("POST", f"/config/config_entries/entry/{entry_id}/reload")})
        return {"reloaded": results, "warning": "This does not reimport Python code; restart Core after source changes."}

    def restart_core(self):
        try:
            self.core("POST", "/services/homeassistant/restart", json={})
        except (httpx.TransportError, httpx.TimeoutException):
            # Restarting Core can terminate the HTTP request early.
            pass
        return {"requested": True, "message": "Core restart requested. Use wait_for_home_assistant to check recovery."}

    def wait_for_core(self, timeout: int = 120):
        timeout = max(10, min(int(timeout), 180))
        deadline = time.monotonic() + timeout
        saw_unavailable = False
        attempts = 0
        time.sleep(3)
        while time.monotonic() < deadline:
            attempts += 1
            try:
                response = self.check()
                if saw_unavailable:
                    return {"online": True, "restart_observed": True, "attempts": attempts, "info": response}
                if attempts >= 6:
                    return {"online": True, "restart_observed": False, "note": "Core is reachable, but a restart could not be confirmed.", "info": response}
            except Exception:
                saw_unavailable = True
            time.sleep(3)
        return {"online": False, "restart_observed": saw_unavailable, "timeout": timeout}

    def light_test(self, domain: str, entity_id: str, service: str, data: dict):
        if service not in {"turn_on", "turn_off"} or not entity_id.startswith(("light.", "switch.")):
            raise ValueError("Only turning lights and switches on or off is allowed")
        entities = {e["entity_id"] for e in self.entity_states(domain)["entities"]}
        if entity_id not in entities:
            raise ValueError("Entity does not belong to this managed integration")
        if not isinstance(data, dict) or set(data) - {"brightness", "brightness_pct", "transition"}:
            raise ValueError("Only brightness, brightness_pct or transition are allowed")
        if entity_id.startswith("switch.") and data:
            raise ValueError("Dimming is available only for light entities")
        for key, maximum in (("brightness", 255), ("brightness_pct", 100), ("transition", 120)):
            if key in data and (not isinstance(data[key], (int, float)) or isinstance(data[key], bool) or not 0 <= data[key] <= maximum):
                raise ValueError(f"Invalid {key}")
        before = self.single_state(entity_id)
        domain_name = entity_id.split(".")[0]
        self.core("POST", f"/services/{domain_name}/{service}", json={"entity_id": entity_id, **data})
        # Device reports may lag; agent can fetch again after an appropriate delay.
        after = self.single_state(entity_id)
        expected_state = "on" if service == "turn_on" else "off"
        target_brightness = (round(float(data["brightness_pct"]) * 255 / 100) if "brightness_pct" in data else data.get("brightness"))
        verified = False
        for attempt in range(5):
            value = after["attributes"].get("brightness")
            verified = after["state"] == expected_state and (target_brightness is None or (isinstance(value, (int, float)) and abs(value - target_brightness) <= 6))
            if verified: break
            time.sleep(2)
            after = self.single_state(entity_id)
        return {"before": before, "after": after, "expected_state": expected_state, "expected_brightness": target_brightness, "verified": verified, "note": "A verified state is a Home Assistant report, not necessarily physical confirmation."}
