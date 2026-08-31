from __future__ import annotations

import threading
from typing import Any


def _as_core_job(row: dict[str, Any]) -> dict[str, Any]:
    job_type = str(row.get("job_type") or "OTHER").upper()
    status = str(row.get("status") or "SUCCESS").upper()
    metrics = {k: v for k, v in row.items() if k not in {
        "id", "schema", "recorded_at", "job_type", "status", "started_at", "finished_at",
        "duration_seconds", "files", "bytes",
    }}
    warning_count = 0
    error_count = 1 if status == "FAILED" else 0
    if job_type == "GITHUB_COMPARE":
        warning_count = int(row.get("local_only") or 0) + int(row.get("divergent") or 0) + int(row.get("unavailable") or 0)
    elif job_type == "INVENTORY":
        warning_count = int(row.get("git_review") or 0) + int(row.get("review") or 0)
    return {
        "program_name": "PC Backup Vault",
        "job_type": job_type,
        "source": "PROJECT_FINDER_LOCAL",
        "source_job_id": str(row.get("id") or "") or None,
        "started_at": row.get("started_at") or row.get("recorded_at"),
        "finished_at": row.get("finished_at") or row.get("recorded_at"),
        "status": status,
        "item_count": int(row.get("files") or 0),
        "byte_count": int(row.get("bytes") or 0),
        "warning_count": max(0, warning_count),
        "error_count": max(0, error_count),
        "duration_seconds": float(row.get("duration_seconds") or 0.0),
        "summary": _summary(row),
        "metrics": metrics,
    }


def _summary(row: dict[str, Any]) -> str:
    kind = str(row.get("job_type") or "OTHER").upper()
    if kind == "INVENTORY":
        return (
            f"Inventur: {int(row.get('files') or 0)} Dateien · "
            f"{int(row.get('to_git') or 0)} zu Git · {int(row.get('duplicates') or 0)} Dubletten"
        )
    if kind == "GITHUB_COMPARE":
        return (
            f"GitHub: {int(row.get('identical') or 0)} identisch · "
            f"{int(row.get('local_only') or 0)} nur lokal · {int(row.get('divergent') or 0)} abweichend"
        )
    return str(row.get("note") or kind)


def mirror_job_best_effort(row: dict[str, Any]) -> bool:
    """Queue a metadata-only Core mirror without ever blocking Project Finder.

    Local history stays authoritative if Core/Neon is unavailable. No exception escapes.
    """
    snapshot = dict(row)
    try:
        thread = threading.Thread(target=_mirror_worker, args=(snapshot,), daemon=True, name="PBV-CoreJobMirror")
        thread.start()
        return True
    except Exception:
        return False


def _mirror_worker(row: dict[str, Any]) -> None:
    try:
        from config_store import ConfigStore, APP_VERSION
        from vault_db import record_core_job

        store = ConfigStore()
        profile = store.get_profile()
        if not profile:
            return
        dsn = store.get_dsn(profile.get("id"))
        if not dsn:
            return
        payload = _as_core_job(row)
        payload["app_version"] = APP_VERSION
        kc = store.data.get("kc_communication") or {}
        payload["device_id"] = str(kc.get("device_id") or "") or None
        record_core_job(dsn, payload)
    except Exception:
        # Deliberately fail-open: a monitoring/control-plane outage must never break inventory.
        return
