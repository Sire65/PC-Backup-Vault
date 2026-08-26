from __future__ import annotations
from pathlib import Path
import psycopg
from status_bus import activity, state

SCHEMA_FILE = Path(__file__).with_name("schema.sql")

def test_connection(dsn: str):
    try:
        activity("neon", "connect")
        with psycopg.connect(dsn, connect_timeout=8) as conn:
            row = conn.execute("SELECT current_database(), version()").fetchone()
            state("neon", "ok", f"{row[0]} – Verbindung OK")
            return True, f"{row[0]} – Verbindung OK"
    except Exception as e:
        state("neon", "error", str(e))
        return False, str(e)


def initialize_schema(dsn: str):
    sql = SCHEMA_FILE.read_text(encoding="utf-8")
    activity("neon", "schema")
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(sql)


def database_size(dsn: str) -> int:
    activity("neon", "read")
    with psycopg.connect(dsn) as conn:
        return int(conn.execute("SELECT pg_database_size(current_database())").fetchone()[0])


def forbidden_tables(dsn: str):
    q = """
      SELECT table_schema || '.' || table_name
      FROM information_schema.tables
      WHERE table_schema NOT IN ('pg_catalog','information_schema','backup_vault','public')
      UNION ALL
      SELECT 'public.' || table_name FROM information_schema.tables WHERE table_schema='public'
    """
    activity("neon", "read")
    with psycopg.connect(dsn) as conn:
        return [r[0] for r in conn.execute(q).fetchall()]


_DASHBOARD_JOB_OPTIONAL_COLUMNS = (
    "directory_count", "active_duration_seconds", "avg_speed_bps", "peak_transfer_bps",
    "compression_saved_bytes", "chunk_count", "largest_file_bytes",
)


def schema_compatibility(dsn: str) -> dict:
    """Return a small, read-only schema capability snapshot for graceful UI fallback."""
    activity("neon", "read")
    with psycopg.connect(dsn, connect_timeout=8) as conn:
        core = conn.execute(
            "SELECT schema_version, app_min_version FROM backup_vault.core WHERE id=1"
        ).fetchone()
        cols = {r[0] for r in conn.execute(
            """SELECT column_name FROM information_schema.columns
               WHERE table_schema='backup_vault' AND table_name='backup_jobs'"""
        ).fetchall()}
        has_verification = bool(conn.execute(
            "SELECT to_regclass('backup_vault.backup_verifications') IS NOT NULL"
        ).fetchone()[0])
    missing = [c for c in _DASHBOARD_JOB_OPTIONAL_COLUMNS if c not in cols]
    return {
        "schema_version": str(core[0]) if core else "unbekannt",
        "app_min_version": str(core[1]) if core else "unbekannt",
        "missing_dashboard_columns": missing,
        "has_verification_table": has_verification,
        "legacy": bool(missing or not has_verification),
    }


def recent_jobs(dsn: str, limit: int = 100):
    """Read jobs across old and current Core schemas without crashing the dashboard."""
    activity("neon", "read")
    with psycopg.connect(dsn) as conn:
        cols = {r[0] for r in conn.execute(
            """SELECT column_name FROM information_schema.columns
               WHERE table_schema='backup_vault' AND table_name='backup_jobs'"""
        ).fetchall()}

        def opt(name: str, fallback: str = "0") -> str:
            return name if name in cols else f"{fallback} AS {name}"

        # Keep this exact field order: dashboard_window.py indexes these tuples.
        select_parts = [
            "id", "started_at", "finished_at", "status", "file_count", "original_bytes",
            "stored_bytes", "deduplicated_bytes", "note", "trigger_type", "plan_name",
            "backup_mode", "scanned_count", "changed_count", "skipped_count", "payload_target",
            opt("directory_count", "0::integer"),
            opt("active_duration_seconds", "0::numeric"),
            opt("avg_speed_bps", "0::bigint"),
            opt("peak_transfer_bps", "0::bigint"),
            opt("compression_saved_bytes", "0::bigint"),
            opt("chunk_count", "0::integer"),
            opt("largest_file_bytes", "0::bigint"),
        ]
        sql = ("SELECT " + ", ".join(select_parts) +
               " FROM backup_vault.backup_jobs ORDER BY started_at DESC LIMIT %s")
        return conn.execute(sql, (limit,)).fetchall()


def all_files(dsn: str, limit: int = 5000):
    activity("neon", "read")
    with psycopg.connect(dsn) as conn:
        return conn.execute("""
          SELECT f.id, f.job_id, f.file_name, f.original_path, f.extension,
                 f.original_size, f.stored_size, f.sha256, f.compression,
                 f.status, f.created_at, f.modified_at, j.trigger_type, j.plan_name, f.payload_backend
          FROM backup_vault.files f
          JOIN backup_vault.backup_jobs j ON j.id=f.job_id
          WHERE f.status IN ('STORED','DEDUPED')
          ORDER BY f.created_at DESC LIMIT %s
        """, (limit,)).fetchall()


def recent_files(dsn: str, limit: int = 500):
    return all_files(dsn, limit)


def recent_restore_tests(dsn: str, limit: int = 200):
    activity("neon", "read")
    with psycopg.connect(dsn) as conn:
        return conn.execute("""
          SELECT run_at, result, hash_match, restored_bytes, details
          FROM backup_vault.restore_tests
          ORDER BY run_at DESC LIMIT %s
        """, (limit,)).fetchall()


def recent_tuev_checks(dsn: str, limit: int = 500):
    activity("neon", "read")
    with psycopg.connect(dsn) as conn:
        return conn.execute("""
          SELECT run_at, check_code, check_name, result, details
          FROM backup_vault.tuev_checks
          ORDER BY run_at DESC LIMIT %s
        """, (limit,)).fetchall()


def usage_history(dsn: str, limit: int = 180):
    activity("neon", "read")
    with psycopg.connect(dsn) as conn:
        return conn.execute("""
          SELECT captured_at, database_bytes, file_payload_bytes, percent_of_hard_limit, status
          FROM backup_vault.usage_snapshots
          ORDER BY captured_at DESC LIMIT %s
        """, (limit,)).fetchall()


def file_status_counts(dsn: str):
    activity("neon", "read")
    with psycopg.connect(dsn) as conn:
        return dict(conn.execute("""
          SELECT status, count(*)::int
          FROM backup_vault.files
          GROUP BY status
        """).fetchall())


def recent_verifications(dsn: str, limit: int = 200):
    # backup_verifications was introduced after Core 1.5.x. Old installations must
    # still be able to open Dashboard/History before the user runs Schema/Core update.
    activity("neon", "read")
    with psycopg.connect(dsn) as conn:
        exists = bool(conn.execute(
            "SELECT to_regclass('backup_vault.backup_verifications') IS NOT NULL"
        ).fetchone()[0])
        if not exists:
            return []
        return conn.execute("""
          SELECT id,job_id,mode,started_at,finished_at,result,checked_files,checked_chunks,
                 checked_bytes,missing_objects,hash_failures,details,app_version
          FROM backup_vault.backup_verifications
          ORDER BY finished_at DESC NULLS LAST,id DESC LIMIT %s
        """, (limit,)).fetchall()
