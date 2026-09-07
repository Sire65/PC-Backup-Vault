from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from pathlib import Path


def _root() -> Path:
    base=Path(os.environ.get("PROGRAMDATA") or Path.home())
    root=base/"PCBackupVault"/"kc_bridge"
    (root/"inbox").mkdir(parents=True,exist_ok=True)
    (root/"results").mkdir(parents=True,exist_ok=True)
    return root


def request_backup(source_program: str, paths, *, job_name=None, target_name=None,
                   filesystem_target_id=None, source_job_id=None) -> str:
    rid=str(uuid.uuid4())
    req={
        "protocol":"KC-PBV-1",
        "request_id":rid,
        "source_job_id":str(source_job_id or rid),
        "source_program":str(source_program or "kc-unknown"),
        "operation":"FILE_BACKUP",
        "job_name":job_name or f"{source_program} Backup",
        "paths":[str(x) for x in (paths or [])],
        "target_name":target_name,
        "filesystem_target_id":filesystem_target_id,
        "submitted_at":datetime.now().astimezone().isoformat(),
    }
    return _enqueue(req)


def request_system_image(source_program: str, *, target_name=None, filesystem_target_id=None,
                         include_volume="C:", source_job_id=None) -> str:
    rid=str(uuid.uuid4())
    req={
        "protocol":"KC-PBV-1","request_id":rid,"source_job_id":str(source_job_id or rid),
        "source_program":str(source_program or "kc-unknown"),"operation":"SYSTEM_IMAGE",
        "target_name":target_name,"filesystem_target_id":filesystem_target_id,
        "include_volume":include_volume,"submitted_at":datetime.now().astimezone().isoformat(),
    }
    return _enqueue(req)


def _enqueue(req: dict) -> str:
    root=_root(); rid=req["request_id"]
    tmp=root/"inbox"/f"{rid}.json.tmp"; final=root/"inbox"/f"{rid}.json"
    tmp.write_text(json.dumps(req,ensure_ascii=False,indent=2),encoding="utf-8"); tmp.replace(final)
    return rid


def backup_status(request_id: str) -> dict:
    root=_root(); result=root/"results"/f"{request_id}.json"
    if result.exists():
        try:return json.loads(result.read_text(encoding="utf-8"))
        except Exception:return {"request_id":request_id,"status":"UNKNOWN","error":"Ergebnisdatei nicht lesbar"}
    if (root/"running"/f"{request_id}.json").exists():return {"request_id":request_id,"status":"RUNNING"}
    if (root/"inbox"/f"{request_id}.json").exists():return {"request_id":request_id,"status":"QUEUED"}
    return {"request_id":request_id,"status":"UNKNOWN"}
