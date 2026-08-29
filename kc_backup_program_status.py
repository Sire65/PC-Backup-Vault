from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Iterable

from kc_backup_scheduler import BackupScheduleJob


STORE_VERSION = 1


@dataclass(frozen=True)
class ProgramRuntimeStatus:
    program_id: str
    last_backup_at: str | None = None
    last_job_id: str | None = None
    verify_status: str | None = None
    last_error: str | None = None

    @property
    def backup_datetime(self) -> datetime | None:
        if not self.last_backup_at:
            return None
        return datetime.fromisoformat(self.last_backup_at)


def load_program_statuses(path: str | Path) -> dict[str, ProgramRuntimeStatus]:
    source = Path(path)
    if not source.exists():
        return {}
    raw = json.loads(source.read_text(encoding="utf-8"))
    if int(raw.get("store_version", 0)) != STORE_VERSION:
        raise ValueError("Unbekannte KC-Programmstatus-Speicherversion")
    result = {}
    for program_id, item in dict(raw.get("programs") or {}).items():
        data = dict(item or {})
        result[program_id] = ProgramRuntimeStatus(
            program_id=program_id,
            last_backup_at=data.get("last_backup_at"),
            last_job_id=data.get("last_job_id"),
            verify_status=data.get("verify_status"),
            last_error=data.get("last_error"),
        )
    return result


def save_program_statuses(path: str | Path, statuses: dict[str, ProgramRuntimeStatus]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "store_version": STORE_VERSION,
        "programs": {
            program_id: {
                "last_backup_at": status.last_backup_at,
                "last_job_id": status.last_job_id,
                "verify_status": status.verify_status,
                "last_error": status.last_error,
            }
            for program_id, status in sorted(statuses.items())
        },
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=target.parent, delete=False, prefix=target.name + ".", suffix=".tmp") as tmp:
        tmp.write(text)
        tmp.flush()
        temp_path = Path(tmp.name)
    temp_path.replace(target)


def record_program_success(
    path: str | Path,
    *,
    program_id: str,
    job_id: str | None,
    verify_status: str = "PASS",
    at: datetime | None = None,
) -> ProgramRuntimeStatus:
    statuses = load_program_statuses(path)
    stamp = (at or datetime.now().astimezone()).isoformat(timespec="seconds")
    status = ProgramRuntimeStatus(
        program_id=program_id,
        last_backup_at=stamp,
        last_job_id=str(job_id) if job_id is not None else None,
        verify_status=str(verify_status or "").upper() or None,
        last_error=None,
    )
    statuses[program_id] = status
    save_program_statuses(path, statuses)
    return status


def record_program_verify(
    path: str | Path,
    *,
    program_id: str,
    verify_status: str,
    error: str | None = None,
) -> ProgramRuntimeStatus:
    """Update verification state without falsifying the last backup timestamp."""
    statuses = load_program_statuses(path)
    previous = statuses.get(program_id, ProgramRuntimeStatus(program_id=program_id))
    status = ProgramRuntimeStatus(
        program_id=program_id,
        last_backup_at=previous.last_backup_at,
        last_job_id=previous.last_job_id,
        verify_status=str(verify_status or "").upper() or None,
        last_error=str(error) if error else None,
    )
    statuses[program_id] = status
    save_program_statuses(path, statuses)
    return status


def record_program_failure(path: str | Path, *, program_id: str, error: str) -> ProgramRuntimeStatus:
    statuses = load_program_statuses(path)
    previous = statuses.get(program_id, ProgramRuntimeStatus(program_id=program_id))
    status = ProgramRuntimeStatus(
        program_id=program_id,
        last_backup_at=previous.last_backup_at,
        last_job_id=previous.last_job_id,
        verify_status=previous.verify_status,
        last_error=str(error),
    )
    statuses[program_id] = status
    save_program_statuses(path, statuses)
    return status


def next_job_for_program(
    jobs: Iterable[BackupScheduleJob],
    program_id: str,
    *,
    now: datetime | None = None,
    horizon_days: int = 370,
) -> datetime | None:
    current = now or datetime.now().astimezone()
    end_date = current.date() + timedelta(days=max(1, int(horizon_days)))
    candidates: list[datetime] = []
    for job in jobs:
        if not job.enabled or job.program_id != program_id:
            continue
        for occurrence in job.occurrences(current.date(), end_date):
            if occurrence >= current.replace(tzinfo=None):
                candidates.append(occurrence)
                break
    return min(candidates) if candidates else None


def traffic_light(*, scope_ready: bool, runtime: ProgramRuntimeStatus | None) -> tuple[str, str]:
    if not scope_ready:
        return "ROT", "Sicherungsumfang nicht vollständig konfiguriert"
    if runtime and runtime.last_error:
        return "ROT", "Letzter Programmlauf hatte einen Fehler"
    if runtime and str(runtime.verify_status or "").upper() == "FAIL":
        return "ROT", "Letzte Vollprüfung fehlgeschlagen"
    if runtime and runtime.last_backup_at and str(runtime.verify_status or "").upper() == "PASS":
        return "GRÜN", "Letzte Sicherung vollständig verifiziert"
    if runtime and runtime.last_backup_at:
        return "GELB", "Sicherung vorhanden, Verify-Status nicht bestätigt"
    return "GELB", "Bereit, aber noch keine bestätigte Sicherung vorhanden"
