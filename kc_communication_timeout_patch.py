"""Runtime patch for KC Communication transport timeouts.

Keeps status/pairing checks on the configured short timeout while giving real
emit operations a separate response budget. This module is intentionally
small so it can be reviewed independently before release integration.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from config_store import APP_NAME, APP_VERSION
import kc_communication as _kc

STATUS_TIMEOUT_SECONDS = 8
EMIT_TIMEOUT_SECONDS = 25


def _post_with_action_timeout(self, payload: dict, authenticated: bool = True) -> dict:
    url = (self.endpoint_url or _kc.DEFAULT_MACHINE_ENDPOINT).strip()
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": f"{APP_NAME}/{APP_VERSION}",
    }
    if authenticated:
        if not self.token:
            raise _kc.KCCommunicationError("KC-Geräte-Token fehlt.")
        headers["x-pbv-device-token"] = self.token

    action = str(payload.get("action") or "event").lower()
    timeout = EMIT_TIMEOUT_SECONDS if action == "emit" else max(2, int(self.timeout or STATUS_TIMEOUT_SECONDS))
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    _kc.activity("kc", "send", action)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(16384).decode("utf-8", errors="replace")
            data = json.loads(raw or "{}") if raw.strip() else {}
            if not 200 <= int(getattr(resp, "status", 200) or 200) < 300:
                raise _kc.KCCommunicationError(f"KC Kommunikation HTTP {resp.status}: {_kc._safe_text(raw,300)}")
            return data if isinstance(data, dict) else {"ok": True}
    except urllib.error.HTTPError as exc:
        raw_detail = exc.read(16384).decode("utf-8", errors="replace")
        obj = {}
        try:
            parsed = json.loads(raw_detail or "{}")
            if isinstance(parsed, dict):
                obj = parsed
        except Exception:
            pass
        detail = str(obj.get("error") or obj.get("detail") or obj.get("message") or raw_detail or f"HTTP {exc.code}")
        raise _kc.KCCommunicationError(f"HTTP {exc.code}: {_kc._safe_text(detail,300)}", exc.code, obj) from exc
    except TimeoutError as exc:
        # A client-side response timeout does not prove that the downstream
        # provider failed. Avoid recording a false provider failure here.
        msg = f"Serverantwort nach {timeout} s noch nicht eingetroffen; Versandstatus unbekannt."
        _kc.state("kc", "warn", msg)
        raise _kc.KCCommunicationError(msg) from exc
    except Exception as exc:
        text = str(exc)
        if "timed out" in text.lower():
            msg = f"Serverantwort nach {timeout} s noch nicht eingetroffen; Versandstatus unbekannt."
            _kc.state("kc", "warn", msg)
            raise _kc.KCCommunicationError(msg) from exc
        _kc.state("kc", "error", text)
        raise _kc.KCCommunicationError(text) from exc


def apply_kc_communication_timeout_patch() -> None:
    if getattr(_kc.KCCommunicationClient, "_kc_timeout_patch_v1932", False):
        return
    _kc.KCCommunicationClient._post = _post_with_action_timeout
    _kc.KCCommunicationClient._kc_timeout_patch_v1932 = True
