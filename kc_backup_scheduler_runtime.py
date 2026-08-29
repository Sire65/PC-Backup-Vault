from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Iterable

from kc_backup_scheduler import BackupScheduleJob, ScheduleAction

STORE_VERSION = 1
_AUTO_ACTIONS = {ScheduleAction.BACKUP, ScheduleAction.VERIFY}
_LOCK = threading.RLock()


@dataclass(frozen=True)
class ScheduledDispatch:
    job_id: str
    program_id: str
    action: ScheduleAction
    scheduled_at: datetime

    @property
    def occurrence_key(self) -> str:
        return f"{self.job_id}@{self.scheduled_at.isoformat(timespec='seconds')}"


def _read(path: Path) -> dict:
    if not path.exists():
        return {"store_version": STORE_VERSION, "occurrences": {}}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if int(raw.get("store_version", 0)) != STORE_VERSION:
        raise ValueError("Unbekannte Scheduler-Runtime-Speicherversion")
    raw.setdefault("occurrences", {})
    return raw


def _write(path: Path, raw: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(raw, ensure_ascii=False, indent=2, sort_keys=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, prefix=path.name + ".", suffix=".tmp") as tmp:
        tmp.write(text)
        tmp.flush()
        temp_path = Path(tmp.name)
    temp_path.replace(path)


def due_dispatches(
    jobs: Iterable[BackupScheduleJob],
    *,
    now: datetime,
    catchup: timedelta = timedelta(hours=6),
) -> list[ScheduledDispatch]:
    """Return the newest due occurrence per job inside the catch-up window.

    RESTORE_TEST is deliberately excluded from unattended execution. Disabled jobs
    and occurrences older than the catch-up window are ignored.
    """
    current = now.replace(tzinfo=None)
    start = current - catchup
    result: list[ScheduledDispatch] = []
    for job in jobs:
        if not job.enabled or job.action not in _AUTO_ACTIONS:
            continue
        occurrences = job.occurrences(start.date(), current.date())
        due = [item for item in occurrences if start <= item <= current]
        if due:
            result.append(ScheduledDispatch(job.job_id, job.program_id, job.action, max(due)))
    return sorted(result, key=lambda item: (item.scheduled_at, item.program_id, item.action.value, item.job_id))


def claim_dispatch(
    path: str | Path,
    dispatch: ScheduledDispatch,
    *,
    now: datetime,
    lease: timedelta = timedelta(hours=2),
) -> bool:
    """Claim one occurrence unless it is complete or has a live lease."""
    target = Path(path)
    with _LOCK:
        raw = _read(target)
        entries = raw["occurrences"]
        previous = dict(entries.get(dispatch.occurrence_key) or {})
        state = str(previous.get("state") or "")
        if state in {"SUCCESS", "BLOCKED", "SKIPPED"}:
            return False
        if state in {"CLAIMED", "RUNNING"} and previous.get("claimed_at"):
            claimed_at = datetime.fromisoformat(previous["claimed_at"])
            if now.replace(tzinfo=None) - claimed_at < lease:
                return False
        entries[dispatch.occurrence_key] = {
            "job_id": dispatch.job_id,
            "program_id": dispatch.program_id,
            "action": dispatch.action.value,
            "scheduled_at": dispatch.scheduled_at.isoformat(timespec="seconds"),
            "state": "CLAIMED",
            "claimed_at": now.replace(tzinfo=None).isoformat(timespec="seconds"),
            "finished_at": None,
            "message": None,
        }
        _write(target, raw)
        return True


def mark_dispatch(
    path: str | Path,
    dispatch: ScheduledDispatch,
    *,
    state: str,
    now: datetime,
    message: str | None = None,
) -> None:
    allowed = {"RUNNING", "SUCCESS", "FAILED", "BLOCKED", "SKIPPED"}
    state = str(state).upper()
    if state not in allowed:
        raise ValueError(f"Ungültiger Scheduler-Status: {state}")
    target = Path(path)
    with _LOCK:
        raw = _read(target)
        entry = dict(raw["occurrences"].get(dispatch.occurrence_key) or {})
        entry.update({
            "job_id": dispatch.job_id,
            "program_id": dispatch.program_id,
            "action": dispatch.action.value,
            "scheduled_at": dispatch.scheduled_at.isoformat(timespec="seconds"),
            "state": state,
            "finished_at": now.replace(tzinfo=None).isoformat(timespec="seconds") if state in {"SUCCESS", "FAILED", "BLOCKED", "SKIPPED"} else None,
            "message": message,
        })
        entry.setdefault("claimed_at", now.replace(tzinfo=None).isoformat(timespec="seconds"))
        raw["occurrences"][dispatch.occurrence_key] = entry
        _write(target, raw)


def occurrence_state(path: str | Path, dispatch: ScheduledDispatch) -> str | None:
    with _LOCK:
        raw = _read(Path(path))
        item = raw["occurrences"].get(dispatch.occurrence_key)
        return str(item.get("state")) if item else None
