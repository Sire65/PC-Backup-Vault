from __future__ import annotations

import os
from pathlib import PureWindowsPath


def normalize_drive_root(path: str) -> str:
    """Return a Windows drive root such as C:\\ for a drive-backed path."""
    p = PureWindowsPath(str(path or ""))
    if not p.drive:
        return str(path or "")
    return p.drive.rstrip("\\/") + "\\"


def is_drive_root(path: str) -> bool:
    text = str(path or "")
    p = PureWindowsPath(text)
    if not p.drive:
        return False
    return text.rstrip("\\/").casefold() == p.drive.rstrip("\\/").casefold()


def get_volume_label(path: str) -> str:
    """Read the Windows volume label without changing or mounting anything."""
    if os.name != "nt":
        return ""
    root = normalize_drive_root(path)
    if not root:
        return ""
    try:
        import ctypes

        name = ctypes.create_unicode_buffer(261)
        fs_name = ctypes.create_unicode_buffer(261)
        serial = ctypes.c_uint32()
        max_component = ctypes.c_uint32()
        flags = ctypes.c_uint32()
        ok = ctypes.windll.kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p(root),
            name,
            len(name),
            ctypes.byref(serial),
            ctypes.byref(max_component),
            ctypes.byref(flags),
            fs_name,
            len(fs_name),
        )
        return name.value.strip() if ok else ""
    except Exception:
        return ""


def format_drive_display(path: str, label: str | None = None) -> str:
    """Human-readable drive label while the caller keeps the original path internally."""
    p = PureWindowsPath(str(path or ""))
    drive = p.drive.rstrip("\\/") if p.drive else str(path or "").rstrip("\\/")
    resolved_label = get_volume_label(path) if label is None else str(label or "").strip()
    if drive and resolved_label:
        return f"{drive}  {resolved_label}"
    return drive or str(path or "")


def format_location_display(path: str) -> str:
    if is_drive_root(path):
        return format_drive_display(path)
    p = PureWindowsPath(str(path or ""))
    return p.name or str(path or "")
