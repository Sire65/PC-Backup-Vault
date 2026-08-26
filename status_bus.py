from __future__ import annotations
import threading
import time
from typing import Callable

_lock = threading.RLock()
_subscribers: list[Callable[[str, str, dict], None]] = []
_last_activity: dict[str, float] = {}
_last_state: dict[str, dict] = {}


def subscribe(callback: Callable[[str, str, dict], None]):
    with _lock:
        if callback not in _subscribers:
            _subscribers.append(callback)
    def unsubscribe():
        with _lock:
            try:
                _subscribers.remove(callback)
            except ValueError:
                pass
    return unsubscribe


def _notify(service: str, event: str, payload: dict):
    with _lock:
        callbacks = list(_subscribers)
    for cb in callbacks:
        try:
            cb(service, event, dict(payload))
        except Exception:
            pass


def activity(service: str, operation: str = "data", detail: str = ""):
    key = str(service or "").lower()
    payload = {"operation": operation, "detail": detail, "at": time.time()}
    with _lock:
        _last_activity[key] = payload["at"]
    _notify(key, "activity", payload)


def state(service: str, level: str, detail: str = ""):
    key = str(service or "").lower()
    payload = {"level": str(level or "unknown").lower(), "detail": detail, "at": time.time()}
    with _lock:
        _last_state[key] = payload
    _notify(key, "state", payload)


def snapshot() -> dict:
    with _lock:
        return {"state": dict(_last_state), "activity": dict(_last_activity)}
