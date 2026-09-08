from __future__ import annotations

import json
import posixpath
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

from unified_reporting_v193 import list_local_job_reports

SCHEMA_VERSION = 2
VAULT_DIR = ".pc-backup-vault"


def archive_path(store) -> Path:
    return Path(store.path).parent / "job_archive.sqlite3"


def _ensure_column(conn, table: str, column: str, ddl: str) -> None:
    cols = {str(r[1]) for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def _connect(store):
    path = archive_path(store)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=15)
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
        CREATE TABLE IF NOT EXISTS storage_locations (
            job_id TEXT NOT NULL,
            location_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            label TEXT,
            backend TEXT,
            transport TEXT,
            account_or_target_id TEXT,
            manifest_ref TEXT,
            availability TEXT,
            last_checked TEXT,
            PRIMARY KEY(job_id, location_id),
            FOREIGN KEY(job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS job_files (
            file_key TEXT PRIMARY KEY,
            job_id TEXT NOT NULL,
            source_file_id TEXT,
            name_cipher TEXT,
            path_cipher TEXT,
            extension TEXT,
            original_size INTEGER NOT NULL DEFAULT 0,
            stored_size INTEGER NOT NULL DEFAULT 0,
            sha256 TEXT,
            modified_at TEXT,
            backend TEXT,
            chunk_count INTEGER NOT NULL DEFAULT 0,
            manifest_ref TEXT,
            indexed_at TEXT NOT NULL,
            FOREIGN KEY(job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS verification_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL,
            event_at TEXT NOT NULL,
            verification_type TEXT,
            status TEXT NOT NULL,
            checked_files INTEGER NOT NULL DEFAULT 0,
            checked_chunks INTEGER NOT NULL DEFAULT 0,
            checked_bytes INTEGER NOT NULL DEFAULT 0,
            missing_objects INTEGER NOT NULL DEFAULT 0,
            hash_errors INTEGER NOT NULL DEFAULT 0,
            details TEXT,
            UNIQUE(job_id,event_at,verification_type,status),
            FOREIGN KEY(job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS restore_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL,
            event_at TEXT NOT NULL,
            status TEXT NOT NULL,
            destination_label TEXT,
            file_count INTEGER NOT NULL DEFAULT 0,
            byte_count INTEGER NOT NULL DEFAULT 0,
            hash_status TEXT,
            details TEXT,
            FOREIGN KEY(job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS job_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL,
            event_at TEXT NOT NULL,
            severity TEXT NOT NULL,
            code TEXT,
            message TEXT NOT NULL,
            FOREIGN KEY(job_id) REFERENCES jobs(job_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_jobs_started ON jobs(started_at DESC, reported_at DESC);
        CREATE INDEX IF NOT EXISTS idx_jobs_target ON jobs(target_label);
        CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
        CREATE INDEX IF NOT EXISTS idx_files_job ON job_files(job_id);
        CREATE INDEX IF NOT EXISTS idx_files_sha ON job_files(sha256);
        CREATE INDEX IF NOT EXISTS idx_restore_job ON restore_events(job_id,event_at DESC);
        CREATE INDEX IF NOT EXISTS idx_verify_job ON verification_events(job_id,event_at DESC);
        """
    )
    _ensure_column(conn, "jobs", "backup_mode", "TEXT")
    _ensure_column(conn, "jobs", "warning_count", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "jobs", "error_count", "INTEGER NOT NULL DEFAULT 0")
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


def _location_id(locator: dict, target_label: str, payload_target: str) -> str:
    kind = str(locator.get("kind") or payload_target or "UNKNOWN").upper()
    ident = str(locator.get("account_id") or locator.get("target_id") or target_label or "default")
    return f"{kind}:{ident}"


def _upsert_storage_location(conn, job_id: str, locator: dict, job: dict) -> None:
    target = str(job.get("target_label") or "–")
    payload = str(job.get("payload_target") or "")
    location_id = _location_id(locator, target, payload)
    conn.execute(
        """INSERT INTO storage_locations(job_id,location_id,kind,label,backend,transport,account_or_target_id,manifest_ref,availability,last_checked)
           VALUES(?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(job_id,location_id) DO UPDATE SET
             label=excluded.label,backend=excluded.backend,transport=excluded.transport,
             account_or_target_id=excluded.account_or_target_id,manifest_ref=COALESCE(excluded.manifest_ref,storage_locations.manifest_ref)""",
        (
            job_id, location_id, str(locator.get("kind") or payload or "UNKNOWN").upper(), target,
            str(job.get("backend_label") or "–"), str(job.get("transport_label") or "–"),
            str(locator.get("account_id") or locator.get("target_id") or "") or None,
            str(locator.get("manifest_ref") or job_id) or None, None, None,
        ),
    )


def _record_verification_from_job(conn, job_id: str, job: dict) -> None:
    v = job.get("verification") or {}
    status = str(v.get("status") or job.get("verification_status") or "").strip()
    if not status or status.lower().startswith("noch nicht") or status == "siehe Datenbankprüfung":
        return
    event_at = _iso(v.get("at") or v.get("checked_at") or job.get("reported_at")) or _now()
    conn.execute(
        """INSERT OR IGNORE INTO verification_events
           (job_id,event_at,verification_type,status,checked_files,checked_chunks,checked_bytes,missing_objects,hash_errors,details)
           VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (
            job_id, event_at, str(v.get("type") or v.get("mode") or "UNKNOWN"), status,
            int(v.get("files") or v.get("checked_files") or 0), int(v.get("chunks") or v.get("checked_chunks") or 0),
            int(v.get("bytes") or v.get("checked_bytes") or 0), int(v.get("missing_objects") or 0),
            int(v.get("hash_errors") or v.get("hashfehler") or 0), str(v.get("details") or "") or None,
        ),
    )


def upsert_job(store, job: dict[str, Any]) -> None:
    job_id = str(job.get("job_id") or "").strip()
    if not job_id:
        return
    verification = job.get("verification") or {}
    locator = job.get("locator") or {}
    with closing(_connect(store)) as conn:
        old = conn.execute("SELECT restore_status,restore_at FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        restore_status = (old["restore_status"] if old else None) or str(job.get("restore_status") or "") or None
        restore_at = (old["restore_at"] if old else None) or _iso(job.get("restore_at"))
        conn.execute(
            """
            INSERT OR REPLACE INTO jobs(
                job_id,started_at,finished_at,reported_at,status,app_version,
                source_label,target_label,source_to_target,backend_label,transport_label,payload_target,
                plan_name,trigger_type,file_count,directory_count,original_bytes,stored_bytes,duration_seconds,
                verification_status,restore_status,restore_at,origin,locator_json,raw_json,updated_at,
                backup_mode,warning_count,error_count
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                job_id,
                _iso(job.get("started_at") or job.get("created_at") or job.get("reported_at")),
                _iso(job.get("finished_at") or job.get("reported_at")),
                _iso(job.get("reported_at") or job.get("finished_at") or job.get("created_at")),
                str(job.get("status") or "UNKNOWN").upper(), str(job.get("app_version") or "") or None,
                str(job.get("source_label") or "–"), str(job.get("target_label") or "–"),
                str(job.get("source_to_target") or "–"), str(job.get("backend_label") or "–"),
                str(job.get("transport_label") or "–"), str(job.get("payload_target") or ""),
                str(job.get("plan_name") or "") or None,
                str(job.get("trigger_type") or ("PLAN" if job.get("plan_name") else "MANUAL")),
                int(job.get("files") or job.get("file_count") or 0), int(job.get("directory_count") or 0),
                int(job.get("original_bytes") or 0), int(job.get("stored_bytes") or 0),
                float(job.get("duration_seconds") or job.get("active_duration_seconds") or 0),
                str(verification.get("status") or job.get("verification_status") or "noch nicht durchgeführt"),
                restore_status, restore_at, str(job.get("origin") or "LOCAL"),
                json.dumps(locator, ensure_ascii=False, default=str), json.dumps(job, ensure_ascii=False, default=str), _now(),
                str(job.get("backup_mode") or job.get("mode") or "") or None,
                int(job.get("warning_count") or 0), int(job.get("error_count") or 0),
            ),
        )
        _upsert_storage_location(conn, job_id, locator, job)
        _record_verification_from_job(conn, job_id, job)
        conn.commit()


def _local_locator(store, report: dict[str, Any]) -> dict[str, Any]:
    target_label = str(report.get("target_label") or "")
    backend = str(report.get("backend_label") or "")
    locator: dict[str, Any] = {"kind": "LOCAL_REPORT", "manifest_ref": str(report.get("job_id") or "")}
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
        job_id = str(r[0]); payload = str(r[15] or "")
        target = "Backblaze B2 + Neon-Core" if payload == "B2" else ("Neon – nur Kleinmengen" if payload == "NEON" else payload or "Neon / B2")
        source = str(r[8] or "") or f"{int(r[4] or 0)} Datei(en)"
        item = {
            "job_id": job_id, "started_at": r[1], "finished_at": r[2], "reported_at": r[2] or r[1], "status": r[3],
            "source_label": source, "target_label": target, "source_to_target": f"{source} → {target}",
            "backend_label": "Backblaze B2" if payload == "B2" else "Neon", "transport_label": "HTTPS / PostgreSQL",
            "payload_target": payload, "plan_name": r[10], "trigger_type": r[9], "backup_mode": r[11],
            "file_count": r[4], "directory_count": r[16], "original_bytes": r[5], "stored_bytes": r[6],
            "duration_seconds": r[17], "verification_status": "siehe Datenbankprüfung", "origin": "NEON",
            "locator": {"kind": "NEON", "job_id": job_id, "payload_target": payload, "manifest_ref": job_id},
        }
        upsert_job(store, item); count += 1
    return count


def _index_file_rows(store, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    with closing(_connect(store)) as conn:
        count = 0
        for item in rows:
            job_id = str(item.get("job_id") or "")
            if not job_id or not conn.execute("SELECT 1 FROM jobs WHERE job_id=?", (job_id,)).fetchone():
                continue
            file_key = str(item.get("file_key") or "").strip()
            if not file_key:
                continue
            conn.execute(
                """INSERT INTO job_files(file_key,job_id,source_file_id,name_cipher,path_cipher,extension,original_size,stored_size,sha256,modified_at,backend,chunk_count,manifest_ref,indexed_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(file_key) DO UPDATE SET
                     job_id=excluded.job_id,name_cipher=excluded.name_cipher,path_cipher=excluded.path_cipher,
                     extension=excluded.extension,original_size=excluded.original_size,stored_size=excluded.stored_size,
                     sha256=excluded.sha256,modified_at=excluded.modified_at,backend=excluded.backend,
                     chunk_count=excluded.chunk_count,manifest_ref=excluded.manifest_ref,indexed_at=excluded.indexed_at""",
                (
                    file_key, job_id, str(item.get("source_file_id") or "") or None,
                    str(item.get("name_cipher") or ""), str(item.get("path_cipher") or ""), str(item.get("extension") or ""),
                    int(item.get("original_size") or 0), int(item.get("stored_size") or 0), str(item.get("sha256") or "") or None,
                    _iso(item.get("modified_at")), str(item.get("backend") or ""), int(item.get("chunk_count") or 0),
                    str(item.get("manifest_ref") or job_id), _now(),
                ),
            ); count += 1
        conn.commit()
    return count


def index_manifest(store, job_id: str, manifest: dict[str, Any], backend: str, manifest_ref: str | None = None) -> int:
    rows = []
    for i, f in enumerate(manifest.get("files") or []):
        sha = str(f.get("sha256") or "")
        rows.append({
            "file_key": f"MANIFEST:{job_id}:{i}:{sha}", "job_id": job_id,
            "name_cipher": f.get("name"), "path_cipher": f.get("path"),
            "extension": Path(str(f.get("name_plain") or "")).suffix.lower() if f.get("name_plain") else "",
            "original_size": f.get("original_size"), "stored_size": sum(int(c.get("bytes") or 0) for c in (f.get("chunks") or [])),
            "sha256": sha, "modified_at": f.get("modified_at"), "backend": backend,
            "chunk_count": len(f.get("chunks") or []), "manifest_ref": manifest_ref or job_id,
        })
    return _index_file_rows(store, rows)


def ingest_neon_files(store, dsn: str | None, limit: int = 50000) -> int:
    if not dsn:
        return 0
    try:
        from vault_db import all_files
        rows = list(all_files(dsn, limit))
    except Exception:
        return 0
    items = []
    for r in rows:
        items.append({
            "file_key": f"DB:{r[0]}", "job_id": str(r[1]), "source_file_id": str(r[0]),
            "name_cipher": r[2], "path_cipher": r[3], "extension": r[4], "original_size": r[5], "stored_size": r[6],
            "sha256": r[7], "modified_at": r[11], "backend": r[14], "chunk_count": 0, "manifest_ref": str(r[1]),
        })
    return _index_file_rows(store, items)


def _filesystem_target(store, locator: dict):
    target_id = str(locator.get("target_id") or "")
    for t in store.data.get("filesystem_targets", []) or []:
        if target_id and str(t.get("id")) == target_id:
            return t
    return None


def index_local_manifests(store) -> int:
    count = 0
    for job in list_jobs(store):
        locator = job.get("locator") or {}
        if str(locator.get("kind") or "").upper() != "FILESYSTEM":
            continue
        target = _filesystem_target(store, locator)
        if not target:
            continue
        path = Path(str(target.get("path") or "")) / VAULT_DIR / "jobs" / f"{job['job_id']}.json"
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
            count += index_manifest(store, job["job_id"], manifest, job.get("backend_label") or "FILESYSTEM")
            _mark_location(store, job["job_id"], "AVAILABLE")
        except Exception:
            continue
    return count


def _mark_location(store, job_id: str, availability: str) -> None:
    with closing(_connect(store)) as conn:
        conn.execute("UPDATE storage_locations SET availability=?,last_checked=? WHERE job_id=?", (availability, _now(), str(job_id)))
        conn.commit()


def index_hidrive_job(app, job_id: str) -> int:
    job = get_job(app.store, job_id)
    if not job:
        return 0
    locator = job.get("locator") or {}
    if str(locator.get("kind") or "").upper() != "HIDRIVE":
        return 0
    account_id = str(locator.get("account_id") or "")
    if not account_id:
        return 0
    try:
        from hidrive_sftp_v192 import _root, sftp_connection
        with sftp_connection(app.store, account_id) as (sftp, account):
            path = posixpath.join(_root(account), VAULT_DIR, "jobs", f"{job_id}.json")
            with sftp.file(path, "rb") as fh:
                manifest = json.loads(fh.read().decode("utf-8"))
        count = index_manifest(app.store, job_id, manifest, "STRATO HiDrive", job_id)
        _mark_location(app.store, job_id, "AVAILABLE")
        return count
    except Exception:
        _mark_location(app.store, job_id, "UNKNOWN")
        return 0


def index_all_hidrive_manifests(app) -> int:
    return sum(index_hidrive_job(app, str(j["job_id"])) for j in list_jobs(app.store) if str((j.get("locator") or {}).get("kind") or "").upper() == "HIDRIVE")


def refresh_archive(store, dsn: str | None = None, recent_jobs_func=None) -> dict[str, int]:
    local = ingest_local_reports(store)
    neon = ingest_neon_jobs(store, dsn, recent_jobs_func) if recent_jobs_func else 0
    files_db = ingest_neon_files(store, dsn)
    files_local = index_local_manifests(store)
    return {"local": local, "neon": neon, "files_db": files_db, "files_local": files_local, "total": archive_count(store)}


def refresh_archive_full(app, recent_jobs_func=None, include_hidrive: bool = True) -> dict[str, int]:
    result = refresh_archive(app.store, app.active_dsn(), recent_jobs_func)
    result["files_hidrive"] = index_all_hidrive_manifests(app) if include_hidrive else 0
    result["files_total"] = archive_file_count(app.store)
    return result


def archive_count(store) -> int:
    with closing(_connect(store)) as conn:
        return int(conn.execute("SELECT count(*) FROM jobs").fetchone()[0])


def archive_file_count(store, job_id: str | None = None) -> int:
    with closing(_connect(store)) as conn:
        if job_id:
            return int(conn.execute("SELECT count(*) FROM job_files WHERE job_id=?", (str(job_id),)).fetchone()[0])
        return int(conn.execute("SELECT count(*) FROM job_files").fetchone()[0])


def list_jobs(store, limit: int = 10000) -> list[dict[str, Any]]:
    with closing(_connect(store)) as conn:
        rows = conn.execute("""SELECT * FROM jobs ORDER BY COALESCE(started_at,reported_at,updated_at) DESC, job_id DESC LIMIT ?""", (max(1, int(limit)),)).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        try: item["locator"] = json.loads(item.pop("locator_json") or "{}")
        except Exception: item["locator"] = {}
        out.append(item)
    return out


def list_job_files(store, job_id: str, limit: int = 100000) -> list[dict[str, Any]]:
    with closing(_connect(store)) as conn:
        rows = conn.execute("SELECT * FROM job_files WHERE job_id=? ORDER BY path_cipher,name_cipher LIMIT ?", (str(job_id), max(1, int(limit)))).fetchall()
    return [dict(r) for r in rows]


def get_job(store, job_id: str) -> dict[str, Any] | None:
    with closing(_connect(store)) as conn:
        row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (str(job_id),)).fetchone()
    if not row: return None
    item = dict(row)
    try: item["locator"] = json.loads(item.pop("locator_json") or "{}")
    except Exception: item["locator"] = {}
    try: item["raw"] = json.loads(item.get("raw_json") or "{}")
    except Exception: item["raw"] = {}
    return item


def record_restore_event(store, job_id: str, status: str, destination_label: str | None = None, file_count: int = 0, byte_count: int = 0, hash_status: str | None = None, details: str | None = None) -> None:
    with closing(_connect(store)) as conn:
        now = _now()
        conn.execute("INSERT INTO restore_events(job_id,event_at,status,destination_label,file_count,byte_count,hash_status,details) VALUES(?,?,?,?,?,?,?,?)",
                     (str(job_id), now, str(status), destination_label, int(file_count or 0), int(byte_count or 0), hash_status, details))
        conn.execute("UPDATE jobs SET restore_status=?,restore_at=?,updated_at=? WHERE job_id=?", (str(status), now, now, str(job_id)))
        conn.commit()


def mark_restore(store, job_id: str, status: str) -> None:
    record_restore_event(store, job_id, status)


def record_job_event(store, job_id: str, severity: str, message: str, code: str | None = None) -> None:
    if not get_job(store, job_id):
        return
    with closing(_connect(store)) as conn:
        conn.execute("INSERT INTO job_events(job_id,event_at,severity,code,message) VALUES(?,?,?,?,?)", (str(job_id), _now(), str(severity).upper(), code, str(message)))
        conn.commit()
