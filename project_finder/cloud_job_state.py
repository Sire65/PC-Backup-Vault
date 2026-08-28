from __future__ import annotations

from dataclasses import dataclass, asdict
import time

TERMINAL = {"SUCCESS", "FAILED", "CANCELLED"}
ACTIVE = {"CLAIMED", "RUNNING"}


@dataclass
class JobLease:
    job_id: str
    device_id: str
    status: str = "QUEUED"
    claimed_by: str = ""
    lease_until: float = 0.0
    attempt: int = 0
    result_digest: str = ""


def claim_job(row: JobLease, *, device_id: str, worker_id: str, now: float | None = None, lease_seconds: int = 300) -> JobLease:
    """Claim a job exactly once per active lease.

    A terminal job cannot be claimed again. Another live worker lease blocks a
    duplicate claim. Expired leases may be reclaimed by the intended device.
    """
    current = time.time() if now is None else float(now)
    if row.device_id != device_id:
        raise PermissionError("Job gehört zu einem anderen Gerät.")
    if row.status in TERMINAL:
        raise RuntimeError("Abgeschlossener Job darf nicht erneut ausgeführt werden.")
    if row.status in ACTIVE and row.lease_until > current and row.claimed_by != worker_id:
        raise RuntimeError("Job besitzt bereits eine aktive Lease.")
    row.status = "CLAIMED"
    row.claimed_by = worker_id
    row.lease_until = current + max(30, int(lease_seconds))
    row.attempt += 1
    return row


def heartbeat(row: JobLease, *, worker_id: str, now: float | None = None, lease_seconds: int = 300) -> JobLease:
    current = time.time() if now is None else float(now)
    if row.status not in ACTIVE or row.claimed_by != worker_id:
        raise PermissionError("Worker besitzt keine aktive Lease.")
    if row.lease_until < current:
        raise RuntimeError("Lease ist abgelaufen.")
    row.status = "RUNNING"
    row.lease_until = current + max(30, int(lease_seconds))
    return row


def finish_job(row: JobLease, *, worker_id: str, status: str, result_digest: str = "") -> JobLease:
    final = status.upper()
    if final not in TERMINAL:
        raise ValueError("Endstatus muss SUCCESS, FAILED oder CANCELLED sein.")
    if row.claimed_by != worker_id or row.status not in ACTIVE:
        raise PermissionError("Nur der aktive Worker darf den Job abschließen.")
    row.status = final
    row.lease_until = 0.0
    row.result_digest = result_digest[:128]
    return row


def to_cloud_row(row: JobLease) -> dict:
    payload = asdict(row)
    payload["schema"] = "kc.project-finder.job-state.v1"
    return payload
