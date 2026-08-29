from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date, time
from pathlib import Path
from tempfile import NamedTemporaryFile

from kc_backup_scheduler import BackupScheduleJob, BackupSafetyProfile, ScheduleFrequency


STORE_VERSION = 1


def _profile_to_dict(profile: BackupSafetyProfile) -> dict:
    return asdict(profile)


def _job_to_dict(job: BackupScheduleJob) -> dict:
    return {
        "job_id": job.job_id,
        "program_id": job.program_id,
        "job_type": job.job_type,
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
    return BackupSafetyProfile(**clean)


def _job_from_dict(raw: dict) -> BackupScheduleJob:
    return BackupScheduleJob(
        program_id=str(raw["program_id"]),
        job_type=str(raw.get("job_type") or "BACKUP"),
        display_name=str(raw.get("display_name") or "Automatische Sicherung"),
        start_date=date.fromisoformat(str(raw["start_date"])),
        start_time=time.fromisoformat(str(raw["start_time"])),
        frequency=ScheduleFrequency(str(raw.get("frequency") or "DAILY")),
        enabled=bool(raw.get("enabled", True)),
        weekday=raw.get("weekday"),
        day_of_month=raw.get("day_of_month"),
        profile=_profile_from_dict(raw.get("profile") or {"name": "KC MAXIMUM"}),
        job_id=str(raw.get("job_id") or "").strip() or None,
    )


def load_jobs(path: str | Path) -> list[BackupScheduleJob]:
    source = Path(path)
    if not source.exists():
        return []
    raw = json.loads(source.read_text(encoding="utf-8"))
    if int(raw.get("store_version", 0)) != STORE_VERSION:
        raise ValueError("Unbekannte Scheduler-Speicherversion")
    jobs = []
    for item in raw.get("jobs", []):
        job = _job_from_dict(item)
        if job.job_id is None:
            raise ValueError("job_id konnte nicht hergestellt werden")
        jobs.append(job)
    return jobs
