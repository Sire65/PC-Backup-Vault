from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from unified_reporting_v193 import list_local_job_reports

SCHEMA_VERSION = 1


def archive_path(store) -> Path:
    return Path(store.path).parent / "job_archive.sqlite3"


def _connect(store):
    path = archive_path(store)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY,
            started_at TEXT,
            finished_at TEXT,
            reported_at TEXT,
            status TEXT NOT NULL,
            app_version TEXT,
            source_label TEXT,
            target_label TEXT,
            source_to_target TEXT,
            backend_label TEXT,
            transport_label TEXT,
            payload_target TEXT,
            plan_name TEXT,
            trigger_type TEXT,
            file_count INTEGER NOT NULL DEFAULT 0,
            directory_count INTEGER NOT NULL DEFAULT 0,
            original_bytes INTEGER NOT NULL DEFAULT 0,
            stored_bytes INTEGER NOT NULL DEFAULT 0,
            duration_seconds REAL NOT NULL DEFAULT 0,
            verification_status TEXT,
            restore_status TEXT,
            restore_at TEXT,
            origin TEXT NOT NULL,
            locator_json TEXT,
            raw_json TEXT,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_jobs_started ON jobs(started_at DESC, reported_at DESC);
        CREATE INDEX IF NOT EXISTS idx_jobs_target ON jobs(target_label);
        CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
        """
    )
    conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('schema_version',?)", (str(SCHEMA_VERSION),))
    conn.commit()
    return conn


def _iso(value) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    text = str(value).strip()
    return text or None


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="microseconds")


def upsert_job(store, job: dict[str, Any]) -> None:
    job_id = str(job.get("job_id") or "").strip()
    if not job_id:
        return
    verification = job.get("verification") or {}
    locator = job.get("locator") or {}
    with _connect(store) as conn:
        old = conn.execute("SELECT restore_status,restore_at FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        restore_status = (old["restore_status"] if old else None) or str(job.get("restore_status") or "") or None
        restore_at = (old["restore_at"] if old else None) or _iso(job.get("restore_at"))
        conn.execute(
            """
            INSERT OR REPLACE INTO jobs(
                job_id,started_at,finished_at,reported_at,status,app_version,
                source_label,target_label,source_to_target,backend_label,transport_label,payload_target,
                plan_name,trigger_type,file_count,directory_count,original_bytes,stored_bytes,duration_seconds,
                verification_status,restore_status,restore_at,origin,locator_json,raw_json,updated_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                job_id,
                _iso(job.get("started_at") or job.get("created_at") or job.get("reported_at")),
                _iso(job.get("finished_at") or job.get("reported_at")),
                _iso(job.get("reported_at") or job.get("finished_at") or job.get("created_at")),
                str(job.get("status") or "UNKNOWN").upper(),
                str(job.get("app_version") or "") or None,
                str(job.get("source_label") or "–"),
                str(job.get("target_label") or "–"),
                str(job.get("source_to_target") or "–"),
                str(job.get("backend_label") or "–"),
                str(job.get("transport_label") or "–"),
                str(job.get("payload_target") or ""),
                str(job.get("plan_name") or "") or None,
                str(job.get("trigger_type") or ("PLAN" if job.get("plan_name") else "MANUAL")),
                int(job.get("files") or job.get("file_count") or 0),
                int(job.get("directory_count") or 0),
                int(job.get("original_bytes") or 0),
                int(job.get("stored_bytes") or 0),
                float(job.get("duration_seconds") or job.get("active_duration_seconds") or 0),
                str(verification.get("status") or job.get("verification_status") or "noch nicht durchgeführt"),
                restore_status,
                restore_at,
                str(job.get("origin") or "LOCAL"),
                json.dumps(locator, ensure_ascii=False, default=str),
                json.dumps(job, ensure_ascii=False, default=str),
                _now(),
            ),
        )
        conn.commit()


def _local_locator(store, report: dict[str, Any]) -> dict[str, Any]:
    target_label = str(report.get("target_label") or "")
    backend = str(report.get("backend_label") or "")
    locator: dict[str, Any] = {"kind": "LOCAL_REPORT"}
    if backend == "STRATO HiDrive" or "hidrive" in target_label.lower():
        locator["kind"] = "HIDRIVE"
        for account in store.data.get("cloud_accounts", []) or []:
            name = str(account.get("name") or "")
            if name and name.lower() in target_label.lower():
                locator["account_id"] = account.get("id")
                locator["account_name"] = name
                break
    else:
        for target in store.data.get("filesystem_targets", []) or []:
            name = str(target.get("name") or "")
            if name and name.lower() in target_label.lower():
                locator.update({"kind": "FILESYSTEM", "target_id": target.get("id"), "target_name": name})
                break
    return locator


def ingest_local_reports(store) -> int:
    count = 0
    for report in list_local_job_reports(store):
        item = dict(report)
        item["origin"] = "LOCAL_REPORT"
        item["locator"] = _local_locator(store, item)
        upsert_job(store, item)
        count += 1
    return count


def ingest_neon_jobs(store, dsn: str | None, recent_jobs_func, limit: int = 5000) -> int:
    if not dsn:
        return 0
    try:
        rows = list(recent_jobs_func(dsn, limit))
    except Exception:
        return 0
    count = 0
    for r in rows:
        job_id = str(r[0])
        payload = str(r[15] or "")
        target = "Backblaze B2 + Neon-Core" if payload == "B2" else ("Neon – nur Kleinmengen" if payload == "NEON" else payload or "Neon / B2")
        source = str(r[8] or "") or f"{int(r[4] or 0)} Datei(en)"
        item = {
            "job_id": job_id,
            "started_at": r[1],
            "finished_at": r[2],
            "reported_at": r[2] or r[1],
            "status": r[3],
            "source_label": source,
            "target_label": target,
            "source_to_target": f"{source} → {target}",
            "backend_label": "Backblaze B2" if payload == "B2" else "Neon",
            "transport_label": "HTTPS / PostgreSQL",
            "payload_target": payload,
            "plan_name": r[10],
            "trigger_type": r[9],
            "file_count": r[4],
            "directory_count": r[16],
            "original_bytes": r[5],
            "stored_bytes": r[6],
            "duration_seconds": r[17],
            "verification_status": "siehe Datenbankprüfung",
            "origin": "NEON",
            "locator": {"kind": "NEON", "job_id": job_id, "payload_target": payload},
        }
        upsert_job(store, item)
        count += 1
    return count


def refresh_archive(store, dsn: str | None = None, recent_jobs_func=None) -> dict[str, int]:
    local = ingest_local_reports(store)
    neon = ingest_neon_jobs(store, dsn, recent_jobs_func) if recent_jobs_func else 0
    return {"local": local, "neon": neon, "total": archive_count(store)}


def archive_count(store) -> int:
    with _connect(store) as conn:
        return int(conn.execute("SELECT count(*) FROM jobs").fetchone()[0])


def list_jobs(store, limit: int = 10000) -> list[dict[str, Any]]:
    with _connect(store) as conn:
        rows = conn.execute(
            """SELECT * FROM jobs
               ORDER BY COALESCE(started_at,reported_at,updated_at) DESC, job_id DESC LIMIT ?""",
            (max(1, int(limit)),),
        ).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        try:
            item["locator"] = json.loads(item.pop("locator_json") or "{}")
        except Exception:
            item["locator"] = {}
        out.append(item)
    return out


def get_job(store, job_id: str) -> dict[str, Any] | None:
    with _connect(store) as conn:
        row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (str(job_id),)).fetchone()
    if not row:
        return None
    item = dict(row)
    try:
        item["locator"] = json.loads(item.pop("locator_json") or "{}")
    except Exception:
        item["locator"] = {}
    try:
        item["raw"] = json.loads(item.get("raw_json") or "{}")
    except Exception:
        item["raw"] = {}
    return item


def mark_restore(store, job_id: str, status: str) -> None:
    with _connect(store) as conn:
        conn.execute(
            "UPDATE jobs SET restore_status=?,restore_at=?,updated_at=? WHERE job_id=?",
            (str(status), _now(), _now(), str(job_id)),
        )
        conn.commit()
