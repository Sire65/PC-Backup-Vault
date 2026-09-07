from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from datetime import datetime
from pathlib import Path

from backup_engine import BackupControl, collect_paths
from crypto_box import encrypt_bytes, encrypt_text, sha256_bytes

VAULT_DIR = ".pc-backup-vault"
CHUNK_SIZE = 8 * 1024 * 1024


def _emit(progress, files_done, files_total, message, metrics=None):
    if not progress:
        return
    metrics = dict(metrics or {})
    try:
        progress(files_done, files_total, message, metrics)
    except TypeError:
        progress(files_done, files_total, message)


def filesystem_backup_improved(app, paths, target, control=None, progress=None, plan_name=None):
    """Filesystem backup with visible preparation/hash progress.

    It also avoids a second recursive directory walk when the caller already supplied
    a concrete file list (as plan_runner does).
    """
    control = control or BackupControl()
    started = time.monotonic()

    supplied = [Path(p) for p in (paths or [])]
    if supplied and all(p.is_file() for p in supplied):
        paths = supplied
    else:
        _emit(progress, 0, 0, "Quellen werden eingelesen …", {
            "phase": "Dateiliste erstellen", "bytes_done": 0, "bytes_total": 0,
            "current_file": "", "elapsed": 0, "speed_bps": 0, "eta_seconds": 0,
        })
        paths = collect_paths(supplied, control=control)

    if not paths:
        raise ValueError("Die festgelegten Quellordner/-dateien sind nicht vorhanden oder leer.")

    total = sum(p.stat().st_size for p in paths)
    _emit(progress, 0, len(paths), f"Dateiliste vorbereitet – {len(paths)} Datei(en)", {
        "phase": "Vorbereitung", "bytes_done": 0, "bytes_total": total,
        "current_file": "", "elapsed": max(0.0, time.monotonic() - started),
        "speed_bps": 0, "eta_seconds": 0,
    })

    root = Path(target["path"]) / VAULT_DIR
    chunks = root / "chunks"
    jobs = root / "jobs"
    chunks.mkdir(parents=True, exist_ok=True)
    jobs.mkdir(parents=True, exist_ok=True)

    probe = root / f".write-test-{os.getpid()}"
    try:
        probe.write_bytes(b"PCBV")
        probe.unlink(missing_ok=True)
    except Exception as exc:
        raise RuntimeError(f"Backup-Ziel ist nicht beschreibbar: {target['path']}\n{exc}") from exc

    done = 0
    files_done = 0
    stored = 0
    peak = 0.0
    manifest = []

    for p in paths:
        control.check()
        stat = p.stat()
        sha = hashlib.sha256()
        hashed = 0
        hash_started = time.monotonic()

        _emit(progress, files_done, len(paths), f"Prüfsumme: {p.name}", {
            "phase": "Prüfsumme", "bytes_done": done, "bytes_total": total,
            "current_file": p.name, "elapsed": max(0.0, time.monotonic() - started),
            "speed_bps": 0, "eta_seconds": 0,
        })

        with p.open("rb") as fh:
            while True:
                control.check()
                block = fh.read(1024 * 1024)
                if not block:
                    break
                sha.update(block)
                hashed += len(block)
                if hashed == len(block) or hashed % (32 * 1024 * 1024) < len(block):
                    h_elapsed = max(0.001, time.monotonic() - hash_started)
                    _emit(progress, files_done, len(paths), f"Prüfsumme: {p.name}", {
                        "phase": "Prüfsumme",
                        "bytes_done": done,
                        "bytes_total": total,
                        "current_file": p.name,
                        "current_file_bytes_done": hashed,
                        "current_file_bytes_total": stat.st_size,
                        "elapsed": max(0.0, time.monotonic() - started),
                        "speed_bps": hashed / h_elapsed,
                        "eta_seconds": max(0.0, (stat.st_size - hashed) / max(1.0, hashed / h_elapsed)),
                    })

        file_sha = sha.hexdigest()
        refs = []
        chunk_no = 0

        with p.open("rb") as fh:
            while True:
                control.check()
                raw = fh.read(CHUNK_SIZE)
                if not raw:
                    break
                aad = f"{file_sha}:{chunk_no}".encode("ascii")
                nonce, cipher = encrypt_bytes(app.master_key(), raw, aad)
                chash = sha256_bytes(cipher)
                rel = Path(file_sha[:2]) / file_sha / f"{chunk_no:06d}-{chash[:12]}.bin"
                out = chunks / rel
                out.parent.mkdir(parents=True, exist_ok=True)
                t0 = time.monotonic()
                if not out.exists():
                    out.write_bytes(nonce + cipher)
                    stored += len(nonce) + len(cipher)
                dt = max(0.001, time.monotonic() - t0)
                speed = (len(nonce) + len(cipher)) / dt
                peak = max(peak, speed)
                refs.append({
                    "no": chunk_no,
                    "file": str(rel).replace("\\", "/"),
                    "cipher_sha256": chash,
                    "bytes": len(nonce) + len(cipher),
                })
                done += len(raw)
                chunk_no += 1
                elapsed = max(0.001, time.monotonic() - started)
                avg = done / elapsed
                eta = (total - done) / avg if avg else 0
                _emit(progress, files_done, len(paths), f"Sichere {p.name}", {
                    "phase": "Dateisystem-Backup",
                    "bytes_done": done,
                    "bytes_total": total,
                    "transfer_bytes": stored,
                    "current_file": p.name,
                    "elapsed": elapsed,
                    "speed_bps": speed,
                    "peak_bps": peak,
                    "eta_seconds": eta,
                })

        manifest.append({
            "path": encrypt_text(app.master_key(), str(p.parent)),
            "name": encrypt_text(app.master_key(), p.name),
            "sha256": file_sha,
            "original_size": stat.st_size,
            "modified_at": stat.st_mtime,
            "chunks": refs,
        })
        files_done += 1

    elapsed = max(0.001, time.monotonic() - started)
    job_id = str(uuid.uuid4())
    doc = {
        "format": "PCBV-FS-1",
        "job_id": job_id,
        "app_version": "1.8.0",
        "created_at": datetime.now().astimezone().isoformat(),
        "plan_name": plan_name,
        "target_name": target.get("name"),
        "files": manifest,
        "file_count": len(manifest),
        "original_bytes": total,
        "stored_bytes": stored,
        "duration_seconds": elapsed,
        "avg_speed_bps": int(total / elapsed),
        "peak_speed_bps": int(peak),
    }
    tmp = jobs / f"{job_id}.json.tmp"
    final = jobs / f"{job_id}.json"
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(final)

    _emit(progress, len(paths), len(paths), "Backup abgeschlossen", {
        "phase": "Fertig", "bytes_done": total, "bytes_total": total,
        "transfer_bytes": stored, "current_file": "", "elapsed": elapsed,
        "speed_bps": 0, "peak_bps": peak, "eta_seconds": 0,
    })
    return {
        "job_id": job_id,
        "status": "SUCCESS",
        "mode": "FILESYSTEM",
        "payload_target": "FILESYSTEM",
        "files": len(manifest),
        "original_bytes": total,
        "stored_bytes": stored,
        "duration_seconds": elapsed,
        "avg_speed_bps": int(total / elapsed),
        "peak_transfer_bps": int(peak),
        "target": str(root),
    }


def apply_filesystem_progress_fix(storage_module):
    storage_module.filesystem_backup = filesystem_backup_improved
