from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from enum import Enum
from typing import Iterable
from uuid import uuid4


class BackupExperience(str, Enum):
    SIMPLE = "SIMPLE"
    ADVANCED = "ADVANCED"
    EXPERT = "EXPERT"


class ScheduleFrequency(str, Enum):
    ONCE = "ONCE"
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"


class ScheduleAction(str, Enum):
    BACKUP = "BACKUP"
    VERIFY = "VERIFY"
    RESTORE_TEST = "RESTORE_TEST"


@dataclass(frozen=True)
class BackupSafetyProfile:
    name: str
    security_level: str = "MAXIMUM"
    preflight: bool = True
    full_verify: bool = True
    create_restore_point: bool = True
    restore_test: bool = True
    require_recovery_material: bool = True
    allow_silent_restore: bool = False
    protect_last_known_good: bool = True


SAFE_DEFAULT_PROFILE = BackupSafetyProfile(name="KC MAXIMUM")


@dataclass(frozen=True)
class OneTouchStep:
    order: int
    job_type: str
    user_label: str
    required: bool = True


@dataclass(frozen=True)
class OneTouchBackupPlan:
    program_id: str
    profile: BackupSafetyProfile = SAFE_DEFAULT_PROFILE
    steps: tuple[OneTouchStep, ...] = (
        OneTouchStep(1, "PREFLIGHT", "Probelauf"),
        OneTouchStep(2, "BACKUP", "Sichern"),
        OneTouchStep(3, "VERIFY", "Vollständig prüfen"),
        OneTouchStep(4, "RESTORE_POINT", "Sicherungspunkt setzen"),
        OneTouchStep(5, "AUDIT", "Ergebnis protokollieren"),
    )

    def visible_summary(self) -> str:
        return "Jetzt sicher sichern"

    def execution_job_types(self) -> tuple[str, ...]:
        return tuple(step.job_type for step in self.steps if step.required)


@dataclass
class BackupScheduleJob:
    program_id: str
    start_date: date
    start_time: time
    frequency: ScheduleFrequency = ScheduleFrequency.DAILY
    action: ScheduleAction = ScheduleAction.BACKUP
    enabled: bool = True
    weekday: int | None = None
    day_of_month: int | None = None
    profile: BackupSafetyProfile = SAFE_DEFAULT_PROFILE
    display_name: str = "Automatische Sicherung"
    job_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        if not self.program_id.strip():
            raise ValueError("program_id darf nicht leer sein")
        if not isinstance(self.frequency, ScheduleFrequency):
            self.frequency = ScheduleFrequency(self.frequency)
        if not isinstance(self.action, ScheduleAction):
            self.action = ScheduleAction(self.action)
        if self.frequency == ScheduleFrequency.WEEKLY:
            if self.weekday is None:
                self.weekday = self.start_date.weekday()
            if not 0 <= self.weekday <= 6:
                raise ValueError("weekday muss zwischen 0 und 6 liegen")
        if self.frequency == ScheduleFrequency.MONTHLY:
            if self.day_of_month is None:
                self.day_of_month = self.start_date.day
            if not 1 <= self.day_of_month <= 31:
                raise ValueError("day_of_month muss zwischen 1 und 31 liegen")

    def occurrences(self, window_start: date, window_end: date) -> list[datetime]:
        if window_end < window_start or not self.enabled:
            return []

        current = max(window_start, self.start_date)
        result: list[datetime] = []
        while current <= window_end:
            if self._matches(current):
                result.append(datetime.combine(current, self.start_time))
                if self.frequency == ScheduleFrequency.ONCE:
                    break
            current += timedelta(days=1)
        return result

    def _matches(self, candidate: date) -> bool:
        if candidate < self.start_date:
            return False
        if self.frequency == ScheduleFrequency.ONCE:
            return candidate == self.start_date
        if self.frequency == ScheduleFrequency.DAILY:
            return True
        if self.frequency == ScheduleFrequency.WEEKLY:
            return candidate.weekday() == self.weekday
        if self.frequency == ScheduleFrequency.MONTHLY:
            return candidate.day == self.day_of_month
        return False


@dataclass(frozen=True)
class CalendarEntry:
    job_id: str
    program_id: str
    starts_at: datetime
    display_name: str
    security_level: str
    action: ScheduleAction


def build_calendar(jobs: Iterable[BackupScheduleJob], window_start: date, window_end: date) -> list[CalendarEntry]:
    entries: list[CalendarEntry] = []
    for job in jobs:
        for occurrence in job.occurrences(window_start, window_end):
            entries.append(
                CalendarEntry(
                    job_id=job.job_id,
                    program_id=job.program_id,
                    starts_at=occurrence,
                    display_name=job.display_name,
                    security_level=job.profile.security_level,
                    action=job.action,
                )
            )
    return sorted(entries, key=lambda item: (item.starts_at, item.program_id, item.action.value, item.job_id))


def default_recurring_jobs(program_id: str, *, backup_time: time = time(2, 0)) -> tuple[BackupScheduleJob, ...]:
    """Safe starter schedule: daily backup, weekly full verification and monthly restore test.

    These objects describe planned jobs only. They never execute backup or restore operations.
    """
    today = date.today()
    return (
        BackupScheduleJob(
            program_id=program_id,
            start_date=today,
            start_time=backup_time,
            frequency=ScheduleFrequency.DAILY,
            action=ScheduleAction.BACKUP,
            display_name="Tägliche sichere Sicherung",
        ),
        BackupScheduleJob(
            program_id=program_id,
            start_date=today,
            start_time=time(3, 0),
            frequency=ScheduleFrequency.WEEKLY,
            weekday=6,
            action=ScheduleAction.VERIFY,
            display_name="Wöchentliche Vollprüfung",
        ),
        BackupScheduleJob(
            program_id=program_id,
            start_date=today,
            start_time=time(4, 0),
            frequency=ScheduleFrequency.MONTHLY,
            day_of_month=1,
            action=ScheduleAction.RESTORE_TEST,
            display_name="Monatlicher Restore-Test",
        ),
    )
