from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

CONTRACT_VERSION = "1.0"
JOB_TYPES = {"PREFLIGHT", "BACKUP", "VERIFY", "RESTORE_TEST", "RESTORE"}
STATUSES = {"RUNNING", "SUCCESS", "WARN", "FAILED", "CANCELLED", "BLOCKED"}
VERIFY_LEVELS = {"NONE", "QUICK", "FULL"}
SECURITY_LEVELS = {"STANDARD", "HIGH", "MAXIMUM"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_program_id(value: str) -> str:
    value = (value or "").strip().lower().replace(" ", "-")
    allowed = "abcdefghijklmnopqrstuvwxyz0123456789-_"
    value = "".join(ch for ch in value if ch in allowed)
    if not value:
        raise ValueError("program_id fehlt oder ist ungueltig")
    return value[:80]


@dataclass(frozen=True)
class KCProgramIdentity:
    program_id: str
    display_name: str
    version: str = "unknown"
    device_id: str = ""
    installation_id: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "program_id": normalize_program_id(self.program_id),
            "display_name": (self.display_name or self.program_id).strip()[:160],
            "version": (self.version or "unknown").strip()[:64],
            "device_id": (self.device_id or "").strip()[:128],
            "installation_id": (self.installation_id or "").strip()[:128],
        }


@dataclass
class KCBackupJobReport:
    identity: KCProgramIdentity
    job_type: str
    status: str
    job_id: str = ""
    started_at: str = field(default_factory=utc_now_iso)
    finished_at: str = ""
    security_level: str = "MAXIMUM"
    verify_level: str = "NONE"
    backup_mode: str = ""
    target: str = ""
    files_total: int = 0
    files_changed: int = 0
    bytes_total: int = 0
    bytes_stored: int = 0
    warnings: int = 0
    errors: int = 0
    message: str = ""
    metrics: Mapping[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        self.identity.as_dict()
        if self.job_type not in JOB_TYPES:
            raise ValueError(f"Unbekannter KC-Jobtyp: {self.job_type}")
        if self.status not in STATUSES:
            raise ValueError(f"Unbekannter KC-Jobstatus: {self.status}")
        if self.security_level not in SECURITY_LEVELS:
            raise ValueError("Ungueltige Sicherheitsstufe")
        if self.verify_level not in VERIFY_LEVELS:
            raise ValueError("Ungueltige Verify-Stufe")
        for value in (self.files_total, self.files_changed, self.bytes_total, self.bytes_stored, self.warnings, self.errors):
            if int(value) < 0:
                raise ValueError("Kennzahlen duerfen nicht negativ sein")

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "contract_version": CONTRACT_VERSION,
            **self.identity.as_dict(),
            "job_id": str(self.job_id or "")[:128],
            "job_type": self.job_type,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "security_level": self.security_level,
            "verify_level": self.verify_level,
            "backup_mode": str(self.backup_mode or "")[:32],
            "target": str(self.target or "")[:64],
            "files_total": int(self.files_total),
            "files_changed": int(self.files_changed),
            "bytes_total": int(self.bytes_total),
            "bytes_stored": int(self.bytes_stored),
            "warnings": int(self.warnings),
            "errors": int(self.errors),
            "message": str(self.message or "")[:1000],
            "metrics": dict(self.metrics or {}),
        }
