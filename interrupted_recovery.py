from __future__ import annotations
import base64, json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config_store import _base_dir
from crypto_box import encrypt_bytes, decrypt_bytes

AAD = b"pc-backup-vault:recovery-checkpoint:v1"
MAGIC = "PBV-RECOVERY-1"


def checkpoint_path() -> Path:
    return _base_dir() / "interrupted_backup.pvrc"


@dataclass
class RecoveryCheckpoint:
    kind: str
    payload: dict[str, Any]
    created_at: str


def _write_encrypted(key_b64: str, document: dict):
    raw = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    nonce, cipher = encrypt_bytes(key_b64, raw, AAD)
    outer = {"magic": MAGIC, "nonce": base64.b64encode(nonce).decode("ascii"), "cipher": base64.b64encode(cipher).decode("ascii")}
    p = checkpoint_path(); tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(outer, separators=(",", ":")), encoding="utf-8")
    tmp.replace(p)


def save_checkpoint(key_b64: str, kind: str, payload: dict[str, Any]):
    _write_encrypted(key_b64, {
        "kind": str(kind or "MANUAL").upper(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "payload": dict(payload or {}),
    })


def save_manual_checkpoint(key_b64: str, paths, backup_mode: str, payload_target: str, job_id: str | None = None):
    save_checkpoint(key_b64, "MANUAL", {
        "paths": [str(Path(p)) for p in paths],
        "backup_mode": str(backup_mode or "AUTO").upper(),
        "payload_target": str(payload_target or "AUTO").upper(),
        "job_id": str(job_id or ""),
    })


def save_plan_checkpoint(key_b64: str, plan_id: str, paths, backup_mode: str, payload_target: str, job_id: str | None = None):
    save_checkpoint(key_b64, "PLAN", {
        "plan_id": str(plan_id),
        "paths": [str(Path(p)) for p in paths],
        "backup_mode": str(backup_mode or "AUTO").upper(),
        "payload_target": str(payload_target or "AUTO").upper(),
        "job_id": str(job_id or ""),
    })


def update_job_id(key_b64: str, job_id: str):
    cp = load_checkpoint(key_b64)
    if not cp:
        return
    payload = dict(cp.payload); payload["job_id"] = str(job_id)
    save_checkpoint(key_b64, cp.kind, payload)


def load_checkpoint(key_b64: str) -> RecoveryCheckpoint | None:
    p = checkpoint_path()
    if not p.exists():
        return None
    outer = json.loads(p.read_text(encoding="utf-8"))
    if outer.get("magic") != MAGIC:
        raise ValueError("Unbekanntes Recovery-Checkpoint-Format.")
    nonce = base64.b64decode(outer["nonce"]); cipher = base64.b64decode(outer["cipher"])
    doc = json.loads(decrypt_bytes(key_b64, nonce, cipher, AAD).decode("utf-8"))
    return RecoveryCheckpoint(str(doc.get("kind") or "MANUAL"), dict(doc.get("payload") or {}), str(doc.get("created_at") or ""))


def clear_checkpoint():
    try: checkpoint_path().unlink(missing_ok=True)
    except Exception: pass


def checkpoint_has_plaintext_paths() -> bool:
    p = checkpoint_path()
    if not p.exists():
        return False
    text = p.read_text(encoding="utf-8", errors="replace")
    return ":\\" in text or ":/" in text or "original_path" in text


def mark_interrupted_job(dsn: str, job_id: str | None) -> bool:
    if not dsn or not job_id:
        return False
    import psycopg
    with psycopg.connect(dsn) as conn:
        row = conn.execute("SELECT status FROM backup_vault.backup_jobs WHERE id=%s", (job_id,)).fetchone()
        if not row or row[0] != "RUNNING":
            return False
        conn.execute(
            """UPDATE backup_vault.backup_jobs
               SET status='INTERRUPTED', recovery_state='RECOVERABLE', interrupted_at=now(), finished_at=COALESCE(finished_at,now()),
                   note=COALESCE(note,'') || CASE WHEN COALESCE(note,'')='' THEN '' ELSE ' | ' END || 'Unerwarteter Programm-/Stromabbruch erkannt.'
               WHERE id=%s""", (job_id,)
        )
        conn.commit(); return True


def discard_recovery(dsn: str | None, job_id: str | None):
    if dsn and job_id:
        try:
            import psycopg
            with psycopg.connect(dsn) as conn:
                conn.execute("UPDATE backup_vault.backup_jobs SET recovery_state='DISCARDED' WHERE id=%s AND status='INTERRUPTED'", (job_id,))
                conn.commit()
        except Exception:
            pass
    clear_checkpoint()
