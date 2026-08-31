from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Optional


def format_bytes(value: int) -> str:
    value = max(0, int(value or 0))
    units = ("B", "KB", "MB", "GB", "TB", "PB")
    amount = float(value)
    for unit in units:
        if amount < 1024.0 or unit == units[-1]:
            if unit == "B":
                return f"{int(amount)} {unit}"
            return f"{amount:.1f} {unit}"
        amount /= 1024.0
    return f"{value} B"


def format_duration(seconds: Optional[float]) -> str:
    if seconds is None or seconds < 0:
        return "–"
    total = int(round(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d} h"
    if minutes:
        return f"{minutes:d}:{secs:02d} min"
    return f"{secs:d} s"


@dataclass(frozen=True)
class OperationProgressSnapshot:
    done: int
    total: int
    percent: float
    elapsed_seconds: float
    eta_seconds: Optional[float]
    rate_per_second: Optional[float]
    items_done: int = 0
    items_total: int = 0
    current_step: str = ""

    @property
    def finished(self) -> bool:
        return self.total > 0 and self.done >= self.total


class OperationProgressTracker:
    """Small reusable progress helper; it is not a new Framework Studio core."""

    def __init__(self, *, started_at: Optional[float] = None):
        self.started_at = time.monotonic() if started_at is None else float(started_at)

    def snapshot(
        self,
        done: int,
        total: int,
        *,
        items_done: int = 0,
        items_total: int = 0,
        current_step: str = "",
        now: Optional[float] = None,
    ) -> OperationProgressSnapshot:
        done = max(0, int(done or 0))
        total = max(0, int(total or 0))
        current = time.monotonic() if now is None else float(now)
        elapsed = max(0.0, current - self.started_at)
        effective_done = min(done, total) if total else done
        percent = min(100.0, effective_done * 100.0 / total) if total else 0.0
        rate = (effective_done / elapsed) if effective_done > 0 and elapsed > 0 else None
        eta = None
        if rate and total > effective_done:
            eta = (total - effective_done) / rate
        elif total > 0 and effective_done >= total:
            eta = 0.0
        return OperationProgressSnapshot(
            done=effective_done,
            total=total,
            percent=percent,
            elapsed_seconds=elapsed,
            eta_seconds=eta,
            rate_per_second=rate,
            items_done=max(0, int(items_done or 0)),
            items_total=max(0, int(items_total or 0)),
            current_step=current_step,
        )


def progress_text(snapshot: OperationProgressSnapshot, *, noun: str = "Dateien") -> str:
    parts = [f"{snapshot.percent:.1f} %"]
    if snapshot.total:
        parts.append(f"{format_bytes(snapshot.done)} / {format_bytes(snapshot.total)}")
    if snapshot.items_total:
        parts.append(f"{snapshot.items_done} / {snapshot.items_total} {noun}")
    parts.append(f"Laufzeit {format_duration(snapshot.elapsed_seconds)}")
    parts.append(f"Restzeit {format_duration(snapshot.eta_seconds)}")
    if snapshot.current_step:
        parts.append(snapshot.current_step)
    return " · ".join(parts)
