from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

ENGINE_PATHS = {
    "R-Studio": (
        r"C:\Program Files\R-Studio\RStudio64.exe",
        r"C:\Program Files (x86)\R-Studio\RStudio.exe",
    ),
    "DMDE": (
        r"C:\Program Files\DMDE\dmde.exe",
        r"C:\Program Files (x86)\DMDE\dmde.exe",
    ),
    "UFS Explorer": (
        r"C:\Program Files\UFS Explorer\ufs-explorer.exe",
        r"C:\Program Files (x86)\UFS Explorer\ufs-explorer.exe",
        r"C:\Program Files\SysDev Laboratories\UFS Explorer\ufs-explorer.exe",
    ),
}

ENGINE_PURPOSE = {
    "R-Studio": "RAID 5/6, mdadm/LVM, Ext/XFS, Images und Vergleichsanalyse",
    "DMDE": "Virtuelles RAID, Parameter-/Reihenfolgeprüfung, Images/Klonen",
    "UFS Explorer": "RAID/mdadm/LVM/Btrfs/Ext/XFS und komplexe NAS-Layouts",
}


@dataclass(frozen=True)
class RecoveryEngine:
    name: str
    installed: bool
    path: str
    purpose: str


def detect_recovery_engines() -> tuple[RecoveryEngine, ...]:
    engines: list[RecoveryEngine] = []
    for name, candidates in ENGINE_PATHS.items():
        found = next((candidate for candidate in candidates if Path(candidate).is_file()), "")
        engines.append(RecoveryEngine(name, bool(found), found, ENGINE_PURPOSE[name]))
    return tuple(engines)


def launch_engine(engine: RecoveryEngine) -> None:
    """Launch an installed recovery tool without passing a physical disk or image automatically."""
    if not engine.installed or not engine.path:
        raise FileNotFoundError(f"{engine.name} wurde nicht gefunden.")
    path = Path(engine.path)
    if not path.is_file():
        raise FileNotFoundError(f"Programmdatei nicht mehr vorhanden: {path}")
    subprocess.Popen([str(path)], creationflags=CREATE_NO_WINDOW)
