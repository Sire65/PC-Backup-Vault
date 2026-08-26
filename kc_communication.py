from __future__ import annotations
import json, re, urllib.error, urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone

from config_store import APP_NAME, APP_VERSION, _base_dir
from status_bus import activity, state

SOURCE_PROGRAM = "pc-backup-vault"
DEFAULT_MACHINE_ENDPOINT = "https://ptblnpiroqftcvlsrhac.supabase.co/functions/v1/kc-communication-machine"
ALLOWED_EVENTS = {
    "backup_success", "backup_warning", "backup_failed", "backup_cancelled",
    "backup_interrupted", "backup_resumed", "verify_failed", "restore_test_failed",
    "tuev_failed", "storage_unreachable", "capacity_warning", "capacity_blocked",
    "scheduler_failed", "communication_test",
}
EVENT_ALIASES = {"tuev_warning": "tuev_failed", "storage_warning": "capacity_warning"}
_ALLOWED_VARS = {
    "jobId", "planName", "status", "statusDetail", "files", "directories", "size",
    "storedSize", "duration", "avgSpeed", "verifyResult", "trigger", "target", "error",
    "warning", "timestamp", "message", "failedChecks", "warningChecks", "mode", "outboxCount",
}
_SENSITIVE_KEY = re.compile(r"(password|passwd|secret|token|dsn|recovery|application_key|access_key|original_path|file_path|path)$", re.I)
_WIN_PATH = re.compile(r"\b[A-Za-z]:[\\/][^\r\n\t]*?(?=(?:\s{2,}|$))")
_DSN = re.compile(r"postgres(?:ql)?://[^\s]+", re.I)


def _safe_text(value, max_len=800) -> str:
    text = str(value or "")
    text = _DSN.sub("[DB-DSN entfernt]", text)
    text = _WIN_PATH.sub("[lokaler Pfad entfernt]", text)
    return text[:max_len]


def _variables(details: dict | None, message: str = "") -> dict:
    src = dict(details or {})
    aliases = {
        "job_id":"jobId", "plan":"planName", "stored_bytes":"storedSize", "original_bytes":"size",
        "avg_speed_bps":"avgSpeed", "verify_result":"verifyResult", "backup_mode":"mode",
    }
    out = {"message": _safe_text(message)} if message else {}
    for k, v in src.items():
        if _SENSITIVE_KEY.search(str(k)):
            continue
        key = aliases.get(str(k), str(k))
        if key not in _ALLOWED_VARS:
            continue
        if isinstance(v, (int, float, bool)) or v is None:
            out[key] = v
        else:
            out[key] = _safe_text(v)
    return out


class KCCommunicationError(RuntimeError):
    def __init__(self, message: str, status: int = 0, data: dict | None = None):
        super().__init__(message)
        self.status = int(status or 0)
        self.data = data if isinstance(data, dict) else {}




def _delivery_summary(data: dict | None) -> tuple[bool, bool, str]:
    """Return (any_success, any_failure, readable summary) for router responses."""
    data = data if isinstance(data, dict) else {}
    results = data.get("results") if isinstance(data.get("results"), list) else []
    channel_states: dict[str, str] = {}
    channel_providers: dict[str, str] = {}
    notes: list[str] = []

    def walk(obj):
        if isinstance(obj, dict):
            # Common provider/result shapes.
            ch = obj.get("channel") or obj.get("selectedChannel") or obj.get("type")
            if isinstance(ch, str) and ch.lower() in ("push", "email"):
                chl = ch.lower()
                provider = obj.get("provider") or obj.get("providerKey") or obj.get("provider_id")
                if provider:
                    channel_providers[chl] = _safe_text(provider,80)
                ok = obj.get("ok")
                status = str(obj.get("status") or "").lower()
                if ok is True or status in ("sent","success","ok","delivered","accepted"):
                    channel_states[chl] = "ok"
                elif ok is False or status in ("failed","error","rejected"):
                    channel_states[chl] = "error"
                    err = obj.get("error") or obj.get("detail") or obj.get("message")
                    if err:
                        notes.append(f"{ch}: {_safe_text(err,220)}")
            for k,v in obj.items():
                if k.lower() in ("token","authorization","apikey","password","secret"):
                    continue
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    walk(results)
    sent = int(data.get("sent") or 0)
    failed = int(data.get("failed") or 0)
    partial_flag = bool(data.get("partial")) or any(bool(r.get("partial")) for r in results if isinstance(r, dict))
    any_success = sent > 0 or partial_flag or any(v == "ok" for v in channel_states.values())
    any_failure = failed > 0 or any(v == "error" for v in channel_states.values()) or data.get("ok") is False

    parts=[]
    for ch,label in (("push","Push"),("email","E-Mail")):
        if ch in channel_states:
            provider = channel_providers.get(ch)
            suffix = f" ({provider})" if provider else ""
            parts.append(f"{label}: {'OK' if channel_states[ch]=='ok' else 'FEHLER'}{suffix}")
    if not parts and partial_flag:
        parts.append("Mindestens ein Kanal erfolgreich, mindestens ein Kanal fehlgeschlagen")
    if notes:
        parts.extend(notes[:3])
    if not parts:
        parts.append(_safe_text(data.get("message") or data.get("error") or "Keine Kanaldetails vom Server", 350))
    return any_success, any_failure, " · ".join(parts)


@dataclass
class KCCommunicationClient:
    endpoint_url: str
    device_id: str
    token: str
    device_name: str = "PC Backup Vault"
    channels: tuple[str, ...] = ("push", "email")
    timeout: int = 8

    def _post(self, payload: dict, authenticated: bool = True) -> dict:
        url = (self.endpoint_url or DEFAULT_MACHINE_ENDPOINT).strip()
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type":"application/json; charset=utf-8", "User-Agent":f"{APP_NAME}/{APP_VERSION}"}
        if authenticated:
            if not self.token:
                raise KCCommunicationError("KC-Geräte-Token fehlt.")
            headers["x-pbv-device-token"] = self.token
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        activity("kc", "send", str(payload.get("action") or "event"))
        try:
            with urllib.request.urlopen(req, timeout=max(2, int(self.timeout or 8))) as resp:
                raw = resp.read(16384).decode("utf-8", errors="replace")
                data = json.loads(raw or "{}") if raw.strip() else {}
                if not 200 <= int(getattr(resp, "status", 200) or 200) < 300:
                    raise KCCommunicationError(f"KC Kommunikation HTTP {resp.status}: {_safe_text(raw,300)}")
                return data if isinstance(data, dict) else {"ok": True}
        except urllib.error.HTTPError as e:
            raw_detail = e.read(16384).decode("utf-8", errors="replace")
            obj = {}
            try:
                parsed = json.loads(raw_detail or "{}")
                if isinstance(parsed, dict):
                    obj = parsed
            except Exception:
                obj = {}
            detail = str(obj.get("error") or obj.get("detail") or obj.get("message") or raw_detail or f"HTTP {e.code}")
            # Die endgültige LED-Bewertung übernimmt send_event(), weil HTTP 502
            # bei KC Communication auch einen Teilerfolg (z. B. Push OK, E-Mail Fehler)
            # enthalten kann.
            raise KCCommunicationError(f"HTTP {e.code}: {_safe_text(detail,300)}", e.code, obj) from e
        except Exception as e:
            state("kc", "error", str(e)); raise KCCommunicationError(str(e)) from e

    def register(self) -> tuple[bool, str, str]:
        if not self.device_id or not self.token:
            return False, "Geräte-ID oder Geräte-Token fehlt.", ""
        try:
            out = self._post({
                "action":"register", "sourceProgram":SOURCE_PROGRAM, "deviceId":self.device_id,
                "deviceName":self.device_name, "token":self.token,
            }, authenticated=False)
            status = str(out.get("status") or "pending")
            code = str(out.get("pairingCode") or "")
            if status == "active":
                state("kc", "ok", "Gerät aktiv gekoppelt"); return True, "KC Kommunikation: Gerät ist aktiv gekoppelt.", code
            state("kc", "warn", f"Pairing ausstehend: {code or 'ohne Code'}")
            return False, f"Gerät registriert. Pairing-Code {code or '–'} muss in KC Communication freigegeben werden.", code
        except Exception as e:
            return False, str(e), ""

    def status(self) -> tuple[bool, str, str]:
        try:
            out = self._post({"action":"status", "sourceProgram":SOURCE_PROGRAM, "deviceId":self.device_id})
            status = str(out.get("status") or "unknown"); code = str(out.get("pairingCode") or "")
            ok = bool(out.get("ok")) and status == "active"
            providers = out.get("providers") if isinstance(out.get("providers"), dict) else {}
            details = []
            for ch,label in (("push","Push"),("email","E-Mail")):
                info = providers.get(ch) if isinstance(providers.get(ch), dict) else None
                if not info:
                    continue
                name = _safe_text(info.get("displayName") or info.get("providerKey") or "unbekannt",100)
                ready = bool(info.get("productionReady"))
                details.append(f"{label}: {name} · {'produktiv' if ready else 'nicht produktionsbereit'}")
            base = "KC Kommunikation aktiv gekoppelt." if ok else f"KC Kommunikation Status: {status}; Pairing-Code {code or '–'}"
            msg = base + (("\n" + "\n".join(details)) if details else "")
            state("kc", "ok" if ok else "warn", msg)
            return ok, msg, code
        except Exception as e:
            return False, str(e), ""

    def test(self) -> tuple[bool, str]:
        ok, msg, _ = self.status(); return ok, msg

    def send_event(self, event: str, title: str, message: str, severity: str = "INFO", details: dict | None = None, channels_override=None) -> tuple[bool, str]:
        event_key = EVENT_ALIASES.get(str(event), str(event))
        if event_key not in ALLOWED_EVENTS:
            return False, f"KC-Ereignis nicht freigegeben: {event_key}"
        chosen = channels_override if channels_override is not None else self.channels
        channels = [c for c in chosen if c in ("push","email")]
        if not channels:
            return False, "Kein KC-Kommunikationskanal ausgewählt."
        sev = str(severity or "INFO").upper()
        priority = "critical" if sev in ("ERROR","CRITICAL","FAIL") else "high" if sev in ("WARN","WARNING") else "normal"
        vars_ = _variables(details, f"{_safe_text(title,180)} – {_safe_text(message,600)}")
        payload = {
            "action":"emit", "sourceProgram":SOURCE_PROGRAM, "deviceId":self.device_id,
            "eventKey":event_key, "channels":channels, "priority":priority,
            "variables":vars_, "correlationId":f"pbv-{self.device_id}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}",
        }
        record = {"sent_at":datetime.now(timezone.utc).isoformat(), "event":event_key, "severity":sev, "message":_safe_text(message)}
        try:
            out = self._post(payload)
            any_success, any_failure, summary = _delivery_summary(out)
            level = "warn" if any_success and any_failure else ("ok" if not any_failure else "error")
            delivery = "PARTIAL" if level == "warn" else ("SENT" if level == "ok" else "FAILED")
            _append_history({**record, "delivery":delivery, "channels":channels, "result":_safe_text(summary,600)})
            state("kc", level, summary if summary else f"{event_key} gesendet")
            return level != "error", summary or "gesendet"
        except KCCommunicationError as e:
            any_success, any_failure, summary = _delivery_summary(e.data)
            if any_success:
                # HTTP 502 kann bei channelMode=all trotz erfolgreich zugestelltem Push auftreten.
                _append_history({**record, "delivery":"PARTIAL", "channels":channels, "http_status":e.status, "result":_safe_text(summary,600)})
                state("kc", "warn", f"TEILERFOLG · {summary}")
                return True, f"TEILERFOLG · {summary}"
            _append_history({**record, "delivery":"FAILED", "channels":channels, "http_status":e.status, "error":_safe_text(summary or e,600)})
            state("kc", "error", f"Versand fehlgeschlagen · {summary or e}")
            return False, summary or str(e)
        except Exception as e:
            _append_history({**record, "delivery":"FAILED", "channels":channels, "error":_safe_text(e,600)})
            state("kc", "error", f"Versand fehlgeschlagen · {_safe_text(e,300)}")
            return False, str(e)

    def diagnose_channel(self, channel: str) -> tuple[bool, str]:
        ch = str(channel or "").lower()
        if ch not in ("push","email"):
            return False, "Unbekannter Kanal."
        return self.send_event(
            "communication_test",
            f"KC Kommunikation – {ch.upper()} Test",
            f"Einzeltest des Kanals {ch}.",
            "INFO",
            {"mode":"diagnostic","status":"TEST","timestamp":datetime.now(timezone.utc).isoformat()},
            channels_override=(ch,)
        )


def _append_history(record: dict):
    try:
        with (_base_dir() / "kc_communication.log").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception: pass


def recent_history(limit: int = 50) -> list[dict]:
    path = _base_dir() / "kc_communication.log"
    if not path.exists(): return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-max(1,limit):]
        out=[]
        for line in reversed(lines):
            try: out.append(json.loads(line))
            except Exception: pass
        return out
    except Exception: return []


def make_client(store) -> KCCommunicationClient | None:
    cfg = dict(store.data.get("kc_communication") or {})
    if not cfg.get("enabled"):
        return None
    token = store.get_kc_device_token() or ""
    device_id = str(cfg.get("device_id") or "")
    if not token or not device_id:
        return None
    channels = tuple(c for c in cfg.get("channels", ["push","email"]) if c in ("push","email"))
    return KCCommunicationClient(
        endpoint_url=str(cfg.get("endpoint_url") or DEFAULT_MACHINE_ENDPOINT), device_id=device_id, token=token,
        device_name=str(cfg.get("device_name") or "PC Backup Vault"), channels=channels,
        timeout=int(cfg.get("timeout_seconds") or 8),
    )
