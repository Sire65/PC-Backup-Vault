from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from typing import Any

from .safety import DEFAULT_POLICY, RecoverySafetyPolicy

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass(frozen=True)
class MissingDiskFinding:
    severity: str
    title: str
    detail: str
    disk_number: int | None = None


@dataclass(frozen=True)
class StorageSnapshot:
    disks: tuple[dict[str, Any], ...]
    physical_disks: tuple[dict[str, Any], ...]
    partitions: tuple[dict[str, Any], ...]
    volumes: tuple[dict[str, Any], ...]
    pnp_disks: tuple[dict[str, Any], ...]


class MissingDiskDetector:
    """Read-only Windows storage discovery for disks missing from Explorer.

    It intentionally uses only inventory/query commands. It never initializes,
    onlines, formats, repairs, assigns drive letters or modifies partition state.
    """

    def __init__(self, policy: RecoverySafetyPolicy | None = None):
        self.policy = policy or DEFAULT_POLICY

    def _powershell_json(self, script: str, timeout: int = 60):
        if os.name != "nt":
            raise RuntimeError("Die Datenträgersuche ist nur unter Windows verfügbar.")
        self.policy.assert_command_safe(script)
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stdout.strip() or "Windows-Speicherinventur fehlgeschlagen.")
        text = completed.stdout.strip()
        return json.loads(text) if text else None

    @staticmethod
    def _rows(value) -> tuple[dict[str, Any], ...]:
        if value is None:
            return ()
        if isinstance(value, list):
            return tuple(v for v in value if isinstance(v, dict))
        if isinstance(value, dict):
            return (value,)
        return ()

    def snapshot(self) -> StorageSnapshot:
        script = r"""
$ErrorActionPreference='Stop'
$result = [ordered]@{}
$result.Disks = @(Get-Disk | Select-Object Number,FriendlyName,SerialNumber,BusType,Size,OperationalStatus,HealthStatus,PartitionStyle,IsOffline,IsReadOnly)
$result.PhysicalDisks = @(Get-PhysicalDisk | Select-Object FriendlyName,SerialNumber,MediaType,BusType,Size,HealthStatus,OperationalStatus,CanPool)
$result.Partitions = @(Get-Partition -ErrorAction SilentlyContinue | Select-Object DiskNumber,PartitionNumber,DriveLetter,Type,Size,Offset,IsActive,IsBoot,IsSystem)
$result.Volumes = @(Get-Volume -ErrorAction SilentlyContinue | Select-Object DriveLetter,FileSystemLabel,FileSystem,HealthStatus,OperationalStatus,Size,SizeRemaining,Path)
$result.PnpDisks = @(Get-PnpDevice -Class DiskDrive -ErrorAction SilentlyContinue | Select-Object Status,FriendlyName,InstanceId,Present)
$result | ConvertTo-Json -Depth 5 -Compress
""".strip()
        raw = self._powershell_json(script, timeout=75) or {}
        return StorageSnapshot(
            disks=self._rows(raw.get("Disks")),
            physical_disks=self._rows(raw.get("PhysicalDisks")),
            partitions=self._rows(raw.get("Partitions")),
            volumes=self._rows(raw.get("Volumes")),
            pnp_disks=self._rows(raw.get("PnpDisks")),
        )

    def evaluate(self, snapshot: StorageSnapshot) -> tuple[MissingDiskFinding, ...]:
        findings: list[MissingDiskFinding] = []
        partitions_by_disk: dict[int, list[dict[str, Any]]] = {}
        for part in snapshot.partitions:
            try:
                number = int(part.get("DiskNumber"))
            except (TypeError, ValueError):
                continue
            partitions_by_disk.setdefault(number, []).append(part)

        volume_letters = {
            str(v.get("DriveLetter") or "").upper()
            for v in snapshot.volumes
            if str(v.get("DriveLetter") or "").strip()
        }

        for disk in snapshot.disks:
            try:
                number = int(disk.get("Number"))
            except (TypeError, ValueError):
                number = None
            name = str(disk.get("FriendlyName") or "Unbekannter Datenträger")
            partition_style = str(disk.get("PartitionStyle") or "").upper()
            health = str(disk.get("HealthStatus") or "")
            operational = disk.get("OperationalStatus")
            if isinstance(operational, list):
                operational = ", ".join(str(x) for x in operational)
            operational = str(operational or "")

            if bool(disk.get("IsOffline")):
                findings.append(MissingDiskFinding("red", f"Disk {number}: offline", f"{name} wird von Windows erkannt, ist aber offline. Nicht initialisieren oder formatieren.", number))
            if partition_style in {"RAW", "UNKNOWN", ""}:
                findings.append(MissingDiskFinding("red", f"Disk {number}: Partitionsstruktur unklar", f"{name}: PartitionStyle={partition_style or 'unbekannt'}. Bei wichtigen Daten keine Initialisierung durchführen.", number))
            if health and health.lower() not in {"healthy", "unbekannt", "unknown"}:
                findings.append(MissingDiskFinding("yellow", f"Disk {number}: Gesundheitswarnung", f"{name}: HealthStatus={health}; OperationalStatus={operational or 'unbekannt'}. Vor weiteren Schritten möglichst Image erstellen.", number))

            parts = partitions_by_disk.get(number, []) if number is not None else []
            if not parts:
                findings.append(MissingDiskFinding("yellow", f"Disk {number}: keine Partition sichtbar", f"{name} ist als Datenträger vorhanden, Windows meldet aber keine Partition. Das kann zu einer im Explorer fehlenden Platte passen.", number))
                continue

            letters = [str(p.get("DriveLetter") or "").upper() for p in parts if str(p.get("DriveLetter") or "").strip()]
            if not letters:
                findings.append(MissingDiskFinding("yellow", f"Disk {number}: kein Laufwerksbuchstabe", f"{name} hat Partition(en), aber keinen Laufwerksbuchstaben. Deshalb kann sie im Explorer fehlen. Noch keinen Buchstaben zuweisen, bevor Dateisystem und Zustand geprüft sind.", number))
            elif all(letter not in volume_letters for letter in letters):
                findings.append(MissingDiskFinding("yellow", f"Disk {number}: Partition ohne eingebundenes Volume", f"{name}: Laufwerksbuchstabe(n) {', '.join(letters)}, aber kein passendes Volume in Get-Volume gefunden.", number))

        present_pnp = [p for p in snapshot.pnp_disks if bool(p.get("Present", True))]
        if present_pnp and not snapshot.disks:
            findings.append(MissingDiskFinding("red", "Hardware sichtbar, Storage-Schicht nicht", "Windows PnP sieht Datenträgerhardware, Get-Disk liefert aber keinen Datenträger. Das spricht für Treiber/Controller/USB-Bridge oder ein tieferes Erkennungsproblem."))

        if not findings:
            findings.append(MissingDiskFinding("green", "Keine offensichtliche Explorer-Abweichung", "Alle von Get-Disk erkannten Datenträger besitzen derzeit eine plausible Windows-Struktur. Wenn die gesuchte Platte trotzdem fehlt, muss geprüft werden, ob sie überhaupt in PnP/BIOS/UEFI erkannt wird."))
        return tuple(findings)

    def run(self) -> tuple[StorageSnapshot, tuple[MissingDiskFinding, ...]]:
        snapshot = self.snapshot()
        return snapshot, self.evaluate(snapshot)
