from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Iterable


def default_history_path() -> Path:
    base = os.environ.get("APPDATA")
    root = Path(base) / "PCBackupVault" if base else Path.home() / ".pc_backup_vault"
    return root / "project_finder_jobs.jsonl"


def append_job(job: dict, path: str | Path | None = None) -> dict:
    target = Path(path) if path else default_history_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    row = dict(job)
    row.setdefault("id", str(uuid.uuid4()))
    row.setdefault("recorded_at", time.strftime("%Y-%m-%dT%H:%M:%S%z"))
    row.setdefault("schema", "pc-backup-vault.project-finder-job.v1")
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    # Core/Neon is an optional control plane. Local append-only history remains authoritative
    # and inventory must never wait for or fail because of the network/database.
    if path is None:
        try:
            from .core_job_bridge import mirror_job_best_effort
            mirror_job_best_effort(row)
        except Exception:
            pass
    return row


def read_jobs(path: str | Path | None = None, limit: int = 2000) -> list[dict]:
    target = Path(path) if path else default_history_path()
    if not target.exists():
        return []
    rows: list[dict] = []
    with target.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except Exception:
                continue
            if isinstance(row, dict):
                rows.append(row)
    rows.sort(key=lambda x: str(x.get("recorded_at") or x.get("finished_at") or ""), reverse=True)
    return rows[: max(1, int(limit))]


def history_kpis(rows: Iterable[dict]) -> dict:
    rows = list(rows)
    inv = [x for x in rows if x.get("job_type") == "INVENTORY"]
    gh = [x for x in rows if x.get("job_type") == "GITHUB_COMPARE"]
    failed = [x for x in rows if x.get("status") == "FAILED"]
    cancelled = [x for x in rows if x.get("status") == "CANCELLED"]
    success = [x for x in rows if x.get("status") == "SUCCESS"]
    total = len(rows)
    return {
        "runs": total,
        "inventory_runs": len(inv),
        "github_runs": len(gh),
        "success": len(success),
        "failed": len(failed),
        "cancelled": len(cancelled),
        "success_percent": round(len(success) / total * 100, 1) if total else 0.0,
        "files_scanned": sum(int(x.get("files") or 0) for x in inv),
        "bytes_scanned": sum(int(x.get("bytes") or 0) for x in inv),
        "to_git": sum(int(x.get("to_git") or 0) for x in inv),
        "duplicates": sum(int(x.get("duplicates") or 0) for x in inv),
        "github_identical": sum(int(x.get("identical") or 0) for x in gh),
        "github_local_only": sum(int(x.get("local_only") or 0) for x in gh),
        "github_divergent": sum(int(x.get("divergent") or 0) for x in gh),
        "github_unavailable": sum(int(x.get("unavailable") or 0) for x in gh),
    }
