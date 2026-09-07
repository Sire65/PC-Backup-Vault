from __future__ import annotations

import json
import os
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path


def _bridge_root(store) -> Path:
    base = Path(os.environ.get("PROGRAMDATA") or store.path.parent)
    root = base / "PCBackupVault" / "kc_bridge"
    (root / "inbox").mkdir(parents=True, exist_ok=True)
    (root / "running").mkdir(parents=True, exist_ok=True)
    (root / "results").mkdir(parents=True, exist_ok=True)
    return root


def submit_request(store, request: dict) -> str:
    """Stable file-based handoff usable by every KC Windows program.

    The source program submits *what* to protect. Secrets and encryption keys are
    never part of the request. The source polls results/<request_id>.json.
    """
    req = dict(request or {})
    rid = str(req.get("request_id") or uuid.uuid4())
    req.update({
        "protocol": "KC-PBV-1",
        "request_id": rid,
        "submitted_at": datetime.now().astimezone().isoformat(),
        "source_program": str(req.get("source_program") or "kc-unknown")[:80],
        "operation": str(req.get("operation") or "FILE_BACKUP").upper(),
    })
    allowed = {"FILE_BACKUP", "SYSTEM_IMAGE"}
    if req["operation"] not in allowed:
        raise ValueError("Unbekannte Backup-Operation.")
    # Explicitly reject secret-like fields at the boundary.
    bad = {"password", "dsn", "token", "secret", "recovery_key", "application_key"}
    if any(k.lower() in bad for k in req):
        raise ValueError("Backup-Anforderung darf keine Zugangsdaten/Schlüssel enthalten.")
    root = _bridge_root(store)
    tmp = root / "inbox" / f"{rid}.json.tmp"
    final = root / "inbox" / f"{rid}.json"
    tmp.write_text(json.dumps(req, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(final)
    return rid


def result_for(store, request_id: str) -> dict | None:
    p = _bridge_root(store) / "results" / f"{request_id}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_result(store, rid, status, **details):
    root = _bridge_root(store)
    payload = {
        "protocol": "KC-PBV-1",
        "request_id": rid,
        "status": status,
        "updated_at": datetime.now().astimezone().isoformat(),
        **details,
    }
    tmp = root / "results" / f"{rid}.json.tmp"
    final = root / "results" / f"{rid}.json"
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(final)


def process_one(app, request_path: Path):
    from backup_engine import collect_paths
    from storage_v180 import _target, filesystem_backup
    from system_image_v180 import create_system_image

    req = json.loads(request_path.read_text(encoding="utf-8"))
    rid = str(req.get("request_id") or request_path.stem)
    root = _bridge_root(app.store)
    running = root / "running" / request_path.name
    request_path.replace(running)
    _write_result(app.store, rid, "RUNNING", source_program=req.get("source_program"))
    try:
        op = str(req.get("operation") or "FILE_BACKUP").upper()
        if op == "SYSTEM_IMAGE":
            target_id = req.get("filesystem_target_id")
            target = _target(app.store, target_id)
            if not target:
                raise ValueError("Systemabbild-Ziel wurde nicht gefunden.")
            result = create_system_image(target, include_volume=req.get("include_volume"), quiet=True)
        else:
            paths = collect_paths(req.get("paths") or [])
            if not paths:
                raise ValueError("Keine erreichbaren Quelldaten in der Backup-Anforderung.")
            target_id = req.get("filesystem_target_id")
            target = _target(app.store, target_id)
            if not target:
                raise ValueError("Backup-Ziel wurde nicht gefunden.")
            result = filesystem_backup(app, paths, target, plan_name=req.get("job_name") or req.get("source_program"))
        _write_result(app.store, rid, "SUCCESS", source_program=req.get("source_program"), result=result)
    except Exception as e:
        _write_result(app.store, rid, "FAILED", source_program=req.get("source_program"), error=str(e))
    finally:
        try: running.unlink(missing_ok=True)
        except Exception: pass


class BridgeWorker:
    def __init__(self, app, interval_seconds=2):
        self.app = app
        self.interval = max(1, int(interval_seconds))
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, name="kc-backup-bridge", daemon=True)
        self.thread.start()

    def _run(self):
        root = _bridge_root(self.app.store)
        while not self.stop_event.is_set():
            for p in sorted((root / "inbox").glob("*.json")):
                if self.stop_event.is_set(): break
                process_one(self.app, p)
            self.stop_event.wait(self.interval)

    def stop(self):
        self.stop_event.set()


def start_bridge(app):
    return BridgeWorker(app)
