from __future__ import annotations

import os
import string
from pathlib import PureWindowsPath
from typing import Iterable

from windows_volume_labels_v1912 import get_volume_label


DRIVE_TYPES = {
    0: "Unbekannt",
    1: "Nicht bereit",
    2: "Wechseldatenträger",
    3: "Lokaler Datenträger",
    4: "Netzlaufwerk",
    5: "CD/DVD",
    6: "RAM-Disk",
}


def normalize_drive_root(value: str) -> str:
    """Normalize a drive-letter location to e.g. ``C:\\``.

    Non drive-letter mount paths are returned unchanged so a future/Windows
    volume mount point can still be represented without inventing a drive.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        p = PureWindowsPath(text)
        drive = str(p.drive or "")
        if len(drive) == 2 and drive[0].isalpha() and drive[1] == ":":
            return drive[0].upper() + ":\\"
    except Exception:
        pass
    return text


def _is_drive_root(value: str) -> bool:
    root = normalize_drive_root(value)
    return len(root) == 3 and root[0].isalpha() and root[1:] == ":\\"


def merge_drive_roots(*groups: Iterable[str]) -> list[str]:
    """Merge independent Windows drive inventories without dropping unready drives."""
    found: dict[str, str] = {}
    for group in groups:
        for raw in group or ():
            root = normalize_drive_root(str(raw or ""))
            if not _is_drive_root(root):
                continue
            found[root.casefold()] = root
    return sorted(found.values(), key=lambda x: x.casefold())


def _python_drives() -> list[str]:
    if not hasattr(os, "listdrives"):
        return []
    try:
        return [str(x) for x in os.listdrives()]
    except Exception:
        return []


def _native_drives() -> list[str]:
    """Read the Windows logical-drive bit mask directly from Kernel32."""
    if os.name != "nt":
        return []
    try:
        import ctypes

        mask = int(ctypes.windll.kernel32.GetLogicalDrives())
        if mask <= 0:
            return []
        return [f"{letter}:\\" for index, letter in enumerate(string.ascii_uppercase) if mask & (1 << index)]
    except Exception:
        return []


def _exists_fallback_drives() -> list[str]:
    """Last-resort fallback for older Python/Windows combinations."""
    if os.name != "nt":
        return []
    rows = []
    for letter in string.ascii_uppercase:
        root = f"{letter}:\\"
        try:
            if os.path.exists(root):
                rows.append(root)
        except Exception:
            pass
    return rows


def discover_drive_roots() -> list[str]:
    """Return every logical Windows drive reported by any supported provider.

    The union is deliberate: a mapped, removable or temporarily unready drive
    must not disappear merely because one discovery API cannot currently probe
    its filesystem. On non-Windows systems the platform anchor is returned for
    test/development usability.
    """
    if os.name != "nt":
        anchor = os.path.abspath(os.sep)
        return [anchor] if anchor else [os.sep]
    return merge_drive_roots(_python_drives(), _native_drives(), _exists_fallback_drives())


def drive_type_code(root: str) -> int:
    if os.name != "nt" or not _is_drive_root(root):
        return 0
    try:
        import ctypes

        return int(ctypes.windll.kernel32.GetDriveTypeW(normalize_drive_root(root)))
    except Exception:
        return 0


def drive_type_label(root: str, code: int | None = None) -> str:
    value = drive_type_code(root) if code is None else int(code)
    return DRIVE_TYPES.get(value, "Unbekannt")


def drive_is_ready(root: str) -> bool:
    try:
        return bool(os.path.exists(normalize_drive_root(root)))
    except Exception:
        return False


def drive_display(root: str, *, label: str | None = None, type_code: int | None = None, ready: bool | None = None) -> str:
    """Explorer-like label while keeping the raw drive root separate internally."""
    raw = normalize_drive_root(root)
    drive = raw.rstrip("\\/") if _is_drive_root(raw) else raw
    volume = get_volume_label(raw) if label is None else str(label or "").strip()
    dtype = drive_type_label(raw, type_code)
    state = drive_is_ready(raw) if ready is None else bool(ready)

    head = f"{drive}  {volume}" if volume else drive
    suffix = dtype
    if not state and dtype not in {"CD/DVD", "Nicht bereit"}:
        suffix += " · nicht erreichbar"
    return f"{head} · {suffix}" if suffix else head


def drive_inventory() -> list[dict]:
    rows = []
    for root in discover_drive_roots():
        code = drive_type_code(root)
        ready = drive_is_ready(root)
        label = get_volume_label(root) if _is_drive_root(root) else ""
        rows.append({
            "root": root,
            "label": label,
            "type_code": code,
            "type": drive_type_label(root, code),
            "ready": ready,
            "display": drive_display(root, label=label, type_code=code, ready=ready),
        })
    return rows
