from __future__ import annotations

import ctypes
import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from .safety import DEFAULT_POLICY, RecoverySafetyPolicy

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass(frozen=True)
class PhysicalDisk:
    number: int
    model: str
    serial: str
    bus: str
    size: int
    status: str
    partition_style: str
    is_offline: bool
    is_read_only: bool

    @property
    def device_path(self) -> str:
        return rf"\\.\PhysicalDrive{self.number}"


@dataclass(frozen=True)
class ReadTestResult:
    device_path: str
    bytes_read: int
    sha256: str


def human_bytes(value: int | float) -> str:
    n = float(value or 0)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if n < 1024 or unit == "PB":
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


class NasRecoveryService:
    """Read-only service layer extracted from NAS Migration Studio v5.6.

    UI code never talks directly to PhysicalDrive devices. All device access runs
    through this service and the RecoverySafetyPolicy gate.
    """

    def __init__(self, policy: RecoverySafetyPolicy | None = None):
        self.policy = policy or DEFAULT_POLICY

    @staticmethod
    def is_admin() -> bool:
        if os.name != "nt":
            return False
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False

    def _powershell(self, script: str, timeout: int = 60) -> tuple[int, str]:
        if os.name != "nt":
            return 127, "Windows PowerShell ist auf diesem System nicht verfügbar."
        self.policy.assert_command_safe(script)
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
        )
        return completed.returncode, completed.stdout

    def scan_disks(self) -> list[PhysicalDisk]:
        script = r"""
$ErrorActionPreference='Stop'
Get-Disk | Select-Object Number,FriendlyName,SerialNumber,BusType,Size,OperationalStatus,PartitionStyle,IsOffline,IsReadOnly | ConvertTo-Json -Depth 3 -Compress
""".strip()
        rc, output = self._powershell(script, timeout=45)
        if rc != 0:
            raise RuntimeError(output.strip() or "Datenträger konnten nicht gelesen werden.")
        text = output.strip()
        if not text:
            return []
        raw = json.loads(text)
        rows = raw if isinstance(raw, list) else [raw]
        disks: list[PhysicalDisk] = []
        for row in rows:
            status = row.get("OperationalStatus")
            if isinstance(status, list):
                status = ", ".join(str(v) for v in status)
            disks.append(
                PhysicalDisk(
                    number=int(row.get("Number") or 0),
                    model=str(row.get("FriendlyName") or ""),
                    serial=str(row.get("SerialNumber") or "").strip(),
                    bus=str(row.get("BusType") or ""),
                    size=int(row.get("Size") or 0),
                    status=str(status or ""),
                    partition_style=str(row.get("PartitionStyle") or ""),
                    is_offline=bool(row.get("IsOffline")),
                    is_read_only=bool(row.get("IsReadOnly")),
                )
            )
        return sorted(disks, key=lambda d: d.number)

    def disk_details(self, disk_number: int) -> str:
        number = int(disk_number)
        script = rf"""
$ErrorActionPreference='Stop'
$disk=Get-Disk -Number {number}
$disk | Format-List Number,FriendlyName,SerialNumber,UniqueId,BusType,Size,OperationalStatus,HealthStatus,PartitionStyle,IsOffline,IsReadOnly | Out-String
Get-Partition -DiskNumber {number} -ErrorAction SilentlyContinue | Format-Table -AutoSize | Out-String
""".strip()
        rc, output = self._powershell(script, timeout=45)
        if rc != 0:
            raise RuntimeError(output.strip() or f"Details für Disk {number} konnten nicht gelesen werden.")
        return output.strip()

    def smart_report(self, disk: PhysicalDisk) -> str:
        smartctl = shutil.which("smartctl")
        if not smartctl:
            candidates = [
                Path(r"C:\Program Files\smartmontools\bin\smartctl.exe"),
                Path(r"C:\Program Files (x86)\smartmontools\bin\smartctl.exe"),
            ]
            smartctl = next((str(p) for p in candidates if p.exists()), None)
        if not smartctl:
            raise RuntimeError("smartctl wurde nicht gefunden. SMART bleibt unverändert; es wird nichts installiert.")
        device = disk.device_path
        self.policy.assert_original_disk_read_only(device, write=False)
        completed = subprocess.run(
            [smartctl, "-a", device],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            timeout=60,
            creationflags=CREATE_NO_WINDOW,
        )
        return completed.stdout.strip()

    def read_test(self, disk: PhysicalDisk, amount: int = 4 * 1024 * 1024) -> ReadTestResult:
        device = disk.device_path
        self.policy.assert_original_disk_read_only(device, write=False)
        digest = hashlib.sha256()
        done = 0
        with open(device, "rb", buffering=0) as handle:
            remaining = int(amount)
            while remaining > 0:
                chunk = handle.read(min(1024 * 1024, remaining))
                if not chunk:
                    break
                digest.update(chunk)
                done += len(chunk)
                remaining -= len(chunk)
        if done == 0:
            raise RuntimeError("Vom Datenträger konnten keine Daten gelesen werden.")
        return ReadTestResult(device, done, digest.hexdigest())

    def create_image(
        self,
        disk: PhysicalDisk,
        destination: str | Path,
        *,
        chunk_size: int = 4 * 1024 * 1024,
        progress: Callable[[int, int], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> Path:
        """Copy one physical disk to an image file without writing to the source.

        The destination file is opened in append mode only for validated resume
        offsets. No repair, mount, RAID assembly or source-disk mutation occurs.
        """
        source = disk.device_path
        target = Path(destination)
        self.policy.assert_original_disk_read_only(source, write=False)
        self.policy.assert_image_destination(source, str(target))
        target.parent.mkdir(parents=True, exist_ok=True)
        resume = target.stat().st_size if target.exists() else 0
        total = int(disk.size or 0)
        if total and resume > total:
            raise RuntimeError("Vorhandene Image-Datei ist größer als der Quelldatenträger; Fortsetzen wurde blockiert.")
        mode = "ab" if resume else "wb"
        done = resume
        with open(source, "rb", buffering=0) as src, open(target, mode) as dst:
            if resume:
                src.seek(resume)
            while True:
                if should_cancel and should_cancel():
                    break
                chunk = src.read(chunk_size)
                if not chunk:
                    break
                dst.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
        return target

    @staticmethod
    def sha256_file(path: str | Path, chunk_size: int = 4 * 1024 * 1024) -> str:
        digest = hashlib.sha256()
        with Path(path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(chunk_size), b""):
                digest.update(chunk)
        return digest.hexdigest()
