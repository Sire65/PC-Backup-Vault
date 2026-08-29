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


@dataclass(frozen=True)
class SchedulerRuntimeSummary:
    last_tick_at: str | None = None
    paused_reason: str | None = None
    due_count: int = 0
    last_started_at: str | None = None
    last_started_program: str | None = None
    last_success_at: str | None = None
    last_success_program: str | None = None
    last_blocked_at: str | None = None
    last_blocked_program: str | None = None
    last_blocked_message: str | None = None
    last_failed_at: str | None = None
    last_failed_program: str | None = None
    last_failed_message: str | None = None


def _empty_store() -> dict:
    return {"store_version": STORE_VERSION, "meta": {}, "occurrences": {}}


def _read(path: Path) -> dict:
    if not path.exists():
        return _empty_store()
    raw = json.loads(path.read_text(encoding="utf-8"))
    if int(raw.get("store_version", 0)) != STORE_VERSION:
        raise ValueError("Unbekannte Scheduler-Runtime-Speicherversion")
    raw.setdefault("meta", {})
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


def record_scheduler_tick(
    path: str | Path,
    *,
    now: datetime,
    paused_reason: str | None = None,
    due_count: int = 0,
) -> None:
    """Write a lightweight heartbeat used only for scheduler observability."""
    target = Path(path)
    with _LOCK:
        raw = _read(target)
        raw["meta"] = {
            "last_tick_at": now.replace(tzinfo=None).isoformat(timespec="seconds"),
            "paused_reason": str(paused_reason) if paused_reason else None,
            "due_count": max(0, int(due_count)),
        }
        _write(target, raw)


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


def runtime_summary(path: str | Path) -> SchedulerRuntimeSummary:
    """Return read-only scheduler health without mutating or dispatching anything."""
    with _LOCK:
        raw = _read(Path(path))
    meta = dict(raw.get("meta") or {})
    entries = list(dict(raw.get("occurrences") or {}).values())

    def latest(state: str):
        matches = [item for item in entries if str(item.get("state") or "").upper() == state]
        if not matches:
            return None
        def stamp(item):
            return str(item.get("finished_at") or item.get("claimed_at") or "")
        return max(matches, key=stamp)

    started = latest("RUNNING") or latest("CLAIMED")
    success = latest("SUCCESS")
    blocked = latest("BLOCKED")
    failed = latest("FAILED")
    return SchedulerRuntimeSummary(
        last_tick_at=meta.get("last_tick_at"),
        paused_reason=meta.get("paused_reason"),
        due_count=int(meta.get("due_count") or 0),
        last_started_at=(started or {}).get("claimed_at"),
        last_started_program=(started or {}).get("program_id"),
        last_success_at=(success or {}).get("finished_at"),
        last_success_program=(success or {}).get("program_id"),
        last_blocked_at=(blocked or {}).get("finished_at"),
        last_blocked_program=(blocked or {}).get("program_id"),
        last_blocked_message=(blocked or {}).get("message"),
        last_failed_at=(failed or {}).get("finished_at"),
        last_failed_program=(failed or {}).get("program_id"),
        last_failed_message=(failed or {}).get("message"),
    )
