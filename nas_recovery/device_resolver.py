from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_DRIVE_RE = re.compile(r"^([A-Za-z]):[\\/]?")


@dataclass(frozen=True)
class PathDeviceResolution:
    path: str
    drive_letter: str
    disk_number: int | None
    device_id: str
    known: bool
    reason: str


def drive_letter_from_path(path: str | Path) -> str:
    match = _DRIVE_RE.match(str(path or "").strip())
    return match.group(1).upper() if match else ""


def parse_disk_resolution(path: str | Path, output: str) -> PathDeviceResolution:
    drive = drive_letter_from_path(path)
    if not drive:
        return PathDeviceResolution(str(path), "", None, "", False, "Kein lokaler Windows-Laufwerksbuchstabe erkannt.")
    try:
        data = json.loads(str(output or "").strip())
        number = int(data.get("DiskNumber"))
        unique = str(data.get("UniqueId") or "").strip()
    except Exception:
        return PathDeviceResolution(str(path), drive, None, "", False, "Datenträgerzuordnung konnte nicht eindeutig gelesen werden.")
    device_id = unique or f"disk-number:{number}"
    return PathDeviceResolution(str(path), drive, number, device_id, True, "Windows-Datenträger read-only zugeordnet.")


class WindowsPathDeviceResolver:
    """Resolve a local path to its backing Windows disk using read-only PowerShell queries only."""

    def resolve(self, path: str | Path) -> PathDeviceResolution:
        drive = drive_letter_from_path(path)
        if not drive:
            return parse_disk_resolution(path, "")
        if os.name != "nt":
            return PathDeviceResolution(str(path), drive, None, "", False, "Windows-Datenträgerauflösung ist auf diesem System nicht verfügbar.")
        script = (
            f"$p=Get-Partition -DriveLetter '{drive}' -ErrorAction Stop; "
            "$d=Get-Disk -Number $p.DiskNumber -ErrorAction Stop; "
            "[pscustomobject]@{DiskNumber=$d.Number;UniqueId=$d.UniqueId}|ConvertTo-Json -Compress"
        )
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            timeout=20,
            creationflags=CREATE_NO_WINDOW,
        )
        if completed.returncode != 0:
            return PathDeviceResolution(str(path), drive, None, "", False, completed.stdout.strip() or "Zuordnung fehlgeschlagen.")
        return parse_disk_resolution(path, completed.stdout)
