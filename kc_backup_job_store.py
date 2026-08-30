from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, time
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import uuid4

from kc_backup_scheduler import (
    BackupScheduleJob,
    BackupSafetyProfile,
    ScheduleAction,
    ScheduleFrequency,
)


STORE_VERSION = 1


@dataclass(frozen=True)
class JobLoadResult:
    jobs: tuple[BackupScheduleJob, ...]
    warnings: tuple[str, ...] = ()


def _profile_to_dict(profile: BackupSafetyProfile) -> dict:
    return asdict(profile)


def _job_to_dict(job: BackupScheduleJob) -> dict:
    return {
        "job_id": job.job_id,
        "program_id": job.program_id,
        "action": job.action.value,
        "display_name": job.display_name,
        "start_date": job.start_date.isoformat(),
        "start_time": job.start_time.strftime("%H:%M:%S"),
        "frequency": job.frequency.value,
        "enabled": bool(job.enabled),
        "weekday": job.weekday,
        "day_of_month": job.day_of_month,
        "profile": _profile_to_dict(job.profile),
    }


def save_jobs(path: str | Path, jobs) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "store_version": STORE_VERSION,
        "jobs": [_job_to_dict(job) for job in jobs],
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=target.parent, delete=False, prefix=target.name + ".", suffix=".tmp") as tmp:
        tmp.write(text)
        tmp.flush()
        temp_path = Path(tmp.name)
    temp_path.replace(target)


def _profile_from_dict(raw: dict) -> BackupSafetyProfile:
    allowed = {
        "name", "security_level", "preflight", "full_verify", "create_restore_point",
        "restore_test", "require_recovery_material", "allow_silent_restore", "protect_last_known_good",
    }
    clean = {key: value for key, value in dict(raw or {}).items() if key in allowed}
    if "name" not in clean:
        clean["name"] = "KC MAXIMUM"
    return BackupSafetyProfile(**clean)


def _job_from_dict(raw: dict) -> BackupScheduleJob:
    if not isinstance(raw, dict):
        raise ValueError("Scheduler-Job ist kein Objekt")
    job_id = str(raw.get("job_id") or "").strip() or str(uuid4())
    return BackupScheduleJob(
        program_id=str(raw["program_id"]),
        action=ScheduleAction(str(raw.get("action") or "BACKUP")),
        display_name=str(raw.get("display_name") or "Automatische Sicherung"),
        start_date=date.fromisoformat(str(raw["start_date"])),
        start_time=time.fromisoformat(str(raw["start_time"])),
        frequency=ScheduleFrequency(str(raw.get("frequency") or "DAILY")),
        enabled=bool(raw.get("enabled", True)),
        weekday=raw.get("weekday"),
        day_of_month=raw.get("day_of_month"),
        profile=_profile_from_dict(raw.get("profile") or {}),
        job_id=job_id,
    )


def _load_raw(path: str | Path) -> dict:
    source = Path(path)
    if not source.exists():
        return {"store_version": STORE_VERSION, "jobs": []}
    raw = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Scheduler-Datei hat kein gültiges Objektformat")
    if int(raw.get("store_version", 0)) != STORE_VERSION:
        raise ValueError("Unbekannte Scheduler-Speicherversion")
    jobs = raw.get("jobs", [])
    if not isinstance(jobs, list):
        raise ValueError("Scheduler-Datei enthält keine gültige Jobliste")
    return raw


def load_jobs_resilient(path: str | Path) -> JobLoadResult:
    """Load valid jobs while quarantining malformed sibling entries in memory only.

    The source file is never rewritten here. Unknown store versions and malformed
    top-level structures remain hard failures.
    """
    raw = _load_raw(path)
    jobs: list[BackupScheduleJob] = []
    warnings: list[str] = []
    for index, item in enumerate(raw.get("jobs", []), start=1):
        try:
            jobs.append(_job_from_dict(item))
        except Exception as exc:
            warnings.append(f"Job #{index} übersprungen: {exc}")
    return JobLoadResult(tuple(jobs), tuple(warnings))


def load_jobs(path: str | Path) -> list[BackupScheduleJob]:
    """Strict editor load: any malformed entry blocks mutation of the source file."""
    result = load_jobs_resilient(path)
    if result.warnings:
        raise ValueError("; ".join(result.warnings))
    return list(result.jobs)
