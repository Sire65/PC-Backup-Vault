from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile

STORE_VERSION = 1


@dataclass(frozen=True)
class SchedulerControl:
    enabled: bool = False


def load_scheduler_control(path: str | Path) -> SchedulerControl:
    source = Path(path)
    if not source.exists():
        return SchedulerControl(enabled=False)
    raw = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or int(raw.get("store_version", 0)) != STORE_VERSION:
        raise ValueError("Unbekannte Scheduler-Steuerungsdatei")
    return SchedulerControl(enabled=bool(raw.get("enabled", False)))


def save_scheduler_control(path: str | Path, control: SchedulerControl) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {"store_version": STORE_VERSION, "enabled": bool(control.enabled)}
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    with NamedTemporaryFile("w", encoding="utf-8", dir=target.parent, delete=False, prefix=target.name + ".", suffix=".tmp") as tmp:
        tmp.write(text)
        tmp.flush()
        temp = Path(tmp.name)
    temp.replace(target)
