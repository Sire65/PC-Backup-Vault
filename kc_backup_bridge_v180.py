from __future__ import annotations

import json
import os
import threading
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
    """Durable handoff usable by every KC Windows program.

    Source applications describe the backup job, never credentials. The source
    polls results/<request_id>.json and can correlate by source_job_id.
    """
    req = dict(request or {})
    rid = str(req.get("request_id") or uuid.uuid4())
    req.update({
        "protocol": "KC-PBV-1",
        "request_id": rid,
        "submitted_at": datetime.now().astimezone().isoformat(),
        "source_program": str(req.get("source_program") or "kc-unknown")[:80],
        "source_job_id": str(req.get("source_job_id") or rid)[:120],
        "operation": str(req.get("operation") or "FILE_BACKUP").upper(),
    })
    if req["operation"] not in {"FILE_BACKUP", "SYSTEM_IMAGE"}:
        raise ValueError("Unbekannte Backup-Operation.")
    forbidden = {"password", "dsn", "token", "secret", "recovery_key", "application_key"}
    if any(k.lower() in forbidden for k in req):
        raise ValueError("Backup-Anforderung darf keine Zugangsdaten/Schlüssel enthalten.")
    root = _bridge_root(store)
    tmp = root / "inbox" / f"{rid}.json.tmp"
    final = root / "inbox" / f"{rid}.json"
    tmp.write_text(json.dumps(req, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(final)
    return rid


def result_for(store, request_id: str) -> dict | None:
    p = _bridge_root(store) / "results" / f"{request_id}.json"
    if not p.exists(): return None
    try: return json.loads(p.read_text(encoding="utf-8"))
    except Exception: return None


def _write_result(store, rid, status, **details):
    root = _bridge_root(store)
    payload = {"protocol":"KC-PBV-1","request_id":rid,"status":status,
               "updated_at":datetime.now().astimezone().isoformat(), **details}
    tmp = root / "results" / f"{rid}.json.tmp"; final = root / "results" / f"{rid}.json"
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"); tmp.replace(final)


def _resolve_target(store, req):
    from storage_v180 import _target, _targets
    tid=req.get("filesystem_target_id")
    if tid:
        t=_target(store,tid)
        if t:return t
    name=str(req.get("target_name") or "").strip().lower()
    if name:
        t=next((x for x in _targets(store) if str(x.get("name") or "").strip().lower()==name),None)
        if t:return t
    return _target(store)


def process_one(app, request_path: Path):
    from backup_engine import collect_paths
    from storage_v180 import filesystem_backup
    from system_image_v180 import create_system_image

    req=json.loads(request_path.read_text(encoding="utf-8")); rid=str(req.get("request_id") or request_path.stem)
    root=_bridge_root(app.store); running=root/"running"/request_path.name; request_path.replace(running)
    common={"source_program":req.get("source_program"),"source_job_id":req.get("source_job_id")}
    _write_result(app.store,rid,"RUNNING",**common)
    try:
        target=_resolve_target(app.store,req)
        if not target: raise ValueError("Kein passendes Backup-Ziel im PC Backup Vault gefunden.")
        op=str(req.get("operation") or "FILE_BACKUP").upper()
        if op=="SYSTEM_IMAGE":
            result=create_system_image(target,include_volume=req.get("include_volume"),quiet=True)
        else:
            paths=collect_paths(req.get("paths") or [])
            if not paths: raise ValueError("Keine erreichbaren Quelldaten in der Backup-Anforderung.")
            result=filesystem_backup(app,paths,target,plan_name=req.get("job_name") or req.get("source_program"))
        _write_result(app.store,rid,"SUCCESS",result=result,**common)
    except Exception as e:
        _write_result(app.store,rid,"FAILED",error=str(e),**common)
    finally:
        try: running.unlink(missing_ok=True)
        except Exception: pass


class BridgeWorker:
    def __init__(self, app, interval_seconds=2):
        self.app=app; self.interval=max(1,int(interval_seconds)); self.stop_event=threading.Event()
        self.thread=threading.Thread(target=self._run,name="kc-backup-bridge",daemon=True); self.thread.start()
    def _run(self):
        root=_bridge_root(self.app.store)
        while not self.stop_event.is_set():
            for p in sorted((root/"inbox").glob("*.json")):
                if self.stop_event.is_set():break
                process_one(self.app,p)
            self.stop_event.wait(self.interval)
    def stop(self):self.stop_event.set()


def start_bridge(app): return BridgeWorker(app)
