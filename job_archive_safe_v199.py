from __future__ import annotations

import json
from contextlib import closing
from typing import Any

import job_archive_v198 as _base


def upsert_job(store, job: dict[str, Any]) -> None:
    """Upsert a job without SQLite REPLACE semantics.

    REPLACE deletes the parent row first and would cascade-delete file/audit rows in
    schema v2. This implementation updates in place so the archive remains durable.
    """
    job_id = str(job.get("job_id") or "").strip()
    if not job_id:
        return
    verification = job.get("verification") or {}
    locator = job.get("locator") or {}
    values = {
        "started_at": _base._iso(job.get("started_at") or job.get("created_at") or job.get("reported_at")),
        "finished_at": _base._iso(job.get("finished_at") or job.get("reported_at")),
        "reported_at": _base._iso(job.get("reported_at") or job.get("finished_at") or job.get("created_at")),
        "status": str(job.get("status") or "UNKNOWN").upper(),
        "app_version": str(job.get("app_version") or "") or None,
        "source_label": str(job.get("source_label") or "–"),
        "target_label": str(job.get("target_label") or "–"),
        "source_to_target": str(job.get("source_to_target") or "–"),
        "backend_label": str(job.get("backend_label") or "–"),
        "transport_label": str(job.get("transport_label") or "–"),
        "payload_target": str(job.get("payload_target") or ""),
        "plan_name": str(job.get("plan_name") or "") or None,
        "trigger_type": str(job.get("trigger_type") or ("PLAN" if job.get("plan_name") else "MANUAL")),
        "file_count": int(job.get("files") or job.get("file_count") or 0),
        "directory_count": int(job.get("directory_count") or 0),
        "original_bytes": int(job.get("original_bytes") or 0),
        "stored_bytes": int(job.get("stored_bytes") or 0),
        "duration_seconds": float(job.get("duration_seconds") or job.get("active_duration_seconds") or 0),
        "verification_status": str(verification.get("status") or job.get("verification_status") or "noch nicht durchgeführt"),
        "origin": str(job.get("origin") or "LOCAL"),
        "locator_json": json.dumps(locator, ensure_ascii=False, default=str),
        "raw_json": json.dumps(job, ensure_ascii=False, default=str),
        "updated_at": _base._now(),
        "backup_mode": str(job.get("backup_mode") or job.get("mode") or "") or None,
        "warning_count": int(job.get("warning_count") or 0),
        "error_count": int(job.get("error_count") or 0),
    }
    with closing(_base._connect(store)) as conn:
        old = conn.execute("SELECT restore_status,restore_at FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        incoming_restore = str(job.get("restore_status") or "") or None
        incoming_restore_at = _base._iso(job.get("restore_at"))
        restore_status = (old["restore_status"] if old else None) or incoming_restore
        restore_at = (old["restore_at"] if old else None) or incoming_restore_at
        if old:
            conn.execute(
                """UPDATE jobs SET
                   started_at=?,finished_at=?,reported_at=?,status=?,app_version=?,source_label=?,target_label=?,
                   source_to_target=?,backend_label=?,transport_label=?,payload_target=?,plan_name=?,trigger_type=?,
                   file_count=?,directory_count=?,original_bytes=?,stored_bytes=?,duration_seconds=?,verification_status=?,
                   restore_status=?,restore_at=?,origin=?,locator_json=?,raw_json=?,updated_at=?,backup_mode=?,warning_count=?,error_count=?
                   WHERE job_id=?""",
                (
                    values["started_at"], values["finished_at"], values["reported_at"], values["status"], values["app_version"],
                    values["source_label"], values["target_label"], values["source_to_target"], values["backend_label"],
                    values["transport_label"], values["payload_target"], values["plan_name"], values["trigger_type"],
                    values["file_count"], values["directory_count"], values["original_bytes"], values["stored_bytes"],
                    values["duration_seconds"], values["verification_status"], restore_status, restore_at, values["origin"],
                    values["locator_json"], values["raw_json"], values["updated_at"], values["backup_mode"],
                    values["warning_count"], values["error_count"], job_id,
                ),
            )
        else:
            conn.execute(
                """INSERT INTO jobs(
                   job_id,started_at,finished_at,reported_at,status,app_version,source_label,target_label,source_to_target,
                   backend_label,transport_label,payload_target,plan_name,trigger_type,file_count,directory_count,
                   original_bytes,stored_bytes,duration_seconds,verification_status,restore_status,restore_at,origin,
                   locator_json,raw_json,updated_at,backup_mode,warning_count,error_count)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    job_id, values["started_at"], values["finished_at"], values["reported_at"], values["status"], values["app_version"],
                    values["source_label"], values["target_label"], values["source_to_target"], values["backend_label"],
                    values["transport_label"], values["payload_target"], values["plan_name"], values["trigger_type"],
                    values["file_count"], values["directory_count"], values["original_bytes"], values["stored_bytes"],
                    values["duration_seconds"], values["verification_status"], restore_status, restore_at, values["origin"],
                    values["locator_json"], values["raw_json"], values["updated_at"], values["backup_mode"],
                    values["warning_count"], values["error_count"],
                ),
            )
        _base._upsert_storage_location(conn, job_id, locator, job)
        _base._record_verification_from_job(conn, job_id, job)
        conn.commit()


# Patch the base module's global lookup so its ingest/refresh functions use the
# non-destructive implementation too.
_base.upsert_job = upsert_job

archive_path = _base.archive_path
_local_locator = _base._local_locator
archive_count = _base.archive_count
archive_file_count = _base.archive_file_count
get_job = _base.get_job
index_manifest = _base.index_manifest
ingest_neon_jobs = _base.ingest_neon_jobs
list_job_files = _base.list_job_files
list_jobs = _base.list_jobs
mark_restore = _base.mark_restore
record_restore_event = _base.record_restore_event
record_job_event = _base.record_job_event
refresh_archive = _base.refresh_archive
refresh_archive_full = _base.refresh_archive_full
index_hidrive_job = _base.index_hidrive_job
