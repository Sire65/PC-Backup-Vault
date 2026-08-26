from __future__ import annotations
import tempfile
from pathlib import Path
import psycopg

from backup_engine import restore_file


def run_restore_selftest(dsn: str, key_b64: str, max_kb: int = 256, object_store_config=None):
    max_bytes = max(1, int(max_kb)) * 1024
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            """
            SELECT id, original_size
            FROM backup_vault.files
            WHERE status IN ('STORED','DEDUPED')
              AND original_size <= %s
            ORDER BY created_at DESC, original_size ASC
            LIMIT 1
            """,
            (max_bytes,),
        ).fetchone()
        if not row:
            return {
                "status": "SKIPPED",
                "details": f"Keine geeignete Testdatei <= {max_kb} KB vorhanden.",
                "bytes": 0,
            }
        file_id, original_size = row

    with tempfile.TemporaryDirectory(prefix="pc_backup_vault_selftest_") as tmp:
        out = restore_file(dsn, key_b64, str(file_id), Path(tmp), object_store_config=object_store_config)
        if not out.exists() or out.stat().st_size != original_size:
            raise ValueError("Restore-Selbsttest: wiederhergestellte Datei ist unvollständig.")
        # TemporaryDirectory removes the restored copy immediately after verification.
        return {
            "status": "PASS",
            "details": "Automatischer Restore-Selbsttest erfolgreich; temporäre Kopie wurde entfernt.",
            "bytes": int(original_size),
        }
