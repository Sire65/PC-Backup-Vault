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
    """Parse `df -h` output conservatively, tolerating wrapped/old NAS formats."""
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


def _likely_data_mount(target: str) -> bool:
    clean = str(target or "").rstrip("/") or "/"
    prefixes = ("/mnt/", "/media/", "/shares/", "/share/", "/volume", "/data", "/raid", "/nfs/")
    return any(clean == p.rstrip("/") or clean.startswith(p) for p in prefixes)


def build_storage_inventory(mount_text: str, df_text: str) -> NasStorageInventory:
    mounts = parse_mount_output(mount_text)
    usage = parse_df_output(df_text)
    candidates = {m.target for m in mounts if _likely_data_mount(m.target)}
    candidates.update(u.mountpoint for u in usage if _likely_data_mount(u.mountpoint))
    return NasStorageInventory(mounts, usage, tuple(sorted(candidates)))


def inventory_from_ssh_report(report) -> NasStorageInventory:
    """Build an inventory from already collected read-only SSH results.

    No second SSH session and no additional shell command is required.
    """
    by_command = {item.command: item.stdout for item in report.results}
    return build_storage_inventory(by_command.get("mount", ""), by_command.get("df -h", ""))
