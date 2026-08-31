from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class MountEntry:
    source: str
    target: str
    fs_type: str
    options: str
    read_only: bool


@dataclass(frozen=True)
class UsageEntry:
    filesystem: str
    size: str
    used: str
    available: str
    percent: str
    mountpoint: str


@dataclass(frozen=True)
class RecoveryAreaAssessment:
    path: str
    category: str
    label: str
    reason: str


@dataclass(frozen=True)
class NasStorageInventory:
    mounts: tuple[MountEntry, ...]
    usage: tuple[UsageEntry, ...]
    likely_data_mounts: tuple[str, ...]


def parse_mount_output(text: str) -> tuple[MountEntry, ...]:
    """Parse Linux `mount` output only; never executes a command."""
    result: list[MountEntry] = []
    rx = re.compile(r"^(.*?) on (.*?) type (\S+) \((.*?)\)$")
    for raw in str(text or "").splitlines():
        m = rx.match(raw.strip())
        if not m:
            continue
        opts = tuple(x.strip() for x in m.group(4).split(",") if x.strip())
        result.append(MountEntry(m.group(1), m.group(2), m.group(3), ",".join(opts), "ro" in opts))
    return tuple(result)


def parse_df_output(text: str) -> tuple[UsageEntry, ...]:
    """Parse standard one-line `df -h` rows conservatively."""
    result: list[UsageEntry] = []
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line or line.lower().startswith("filesystem"):
            continue
        parts = line.split()
        if len(parts) < 6 or not parts[-2].endswith("%"):
            continue
        result.append(UsageEntry(parts[0], parts[1], parts[2], parts[3], parts[-2], parts[-1]))
    return tuple(result)


def _path_is_or_below(path: str, root: str) -> bool:
    clean = "/" + str(path or "").strip().strip("/")
    root_clean = "/" + str(root or "").strip().strip("/")
    return clean == root_clean or clean.startswith(root_clean + "/")


def _likely_data_mount(target: str) -> bool:
    clean = str(target or "").strip() or "/"
    roots = ("/mnt", "/media", "/shares", "/share", "/volume", "/data", "/raid", "/nfs")
    return any(_path_is_or_below(clean, root) for root in roots)


def classify_recovery_area(path: str, fs_type: str = "", source: str = "") -> RecoveryAreaAssessment:
    """Heuristic classification only; it never grants write permission or starts recovery."""
    clean = str(path or "").strip() or "/"
    system_roots = ("/", "/boot", "/proc", "/sys", "/dev", "/run", "/etc", "/var", "/usr", "/bin", "/sbin", "/lib", "/lib64")
    if clean == "/" or any(_path_is_or_below(clean, root) for root in system_roots[1:]):
        return RecoveryAreaAssessment(clean, "system", "System – nicht für Recovery auswählen", "typischer Betriebssystem-/Laufzeitbereich")
    if _likely_data_mount(clean):
        return RecoveryAreaAssessment(clean, "data", "Daten – Recovery-Kandidat", "typischer NAS-Datenpfad; vor Auswahl trotzdem prüfen")
    return RecoveryAreaAssessment(clean, "review", "Unklar – erst prüfen", "Pfad ist weder eindeutig System noch typischer Datenbereich")


def build_storage_inventory(mount_text: str, df_text: str) -> NasStorageInventory:
    mounts = parse_mount_output(mount_text)
    usage = parse_df_output(df_text)
    candidates = {m.target for m in mounts if classify_recovery_area(m.target, m.fs_type, m.source).category == "data"}
    candidates.update(u.mountpoint for u in usage if classify_recovery_area(u.mountpoint, source=u.filesystem).category == "data")
    return NasStorageInventory(mounts, usage, tuple(sorted(candidates)))


def inventory_from_ssh_report(report) -> NasStorageInventory:
    """Build an inventory from already collected read-only SSH results.

    No second SSH session and no additional shell command is required.
    """
    by_command = {item.command: item.stdout for item in report.results}
    return build_storage_inventory(by_command.get("mount", ""), by_command.get("df -h", ""))
