from __future__ import annotations

import os

from windows_drive_inventory_v1924 import drive_inventory, normalize_drive_root


def drive_inventory_check() -> tuple[str, str, str, str]:
    """Return a normal TÜV row describing the real Windows drive inventory."""
    rows = drive_inventory()
    if os.name != "nt":
        return ("DRV-001", "Windows-Laufwerksinventar", "PASS", "Nicht-Windows-Prüfsystem · Laufwerkslogik importierbar")

    if not rows:
        return ("DRV-001", "Windows-Laufwerksinventar", "FAIL", "Windows meldet kein logisches Laufwerk")

    system_drive = normalize_drive_root(os.environ.get("SystemDrive") or os.environ.get("SYSTEMDRIVE") or "C:")
    roots = {str(row.get("root") or "").casefold() for row in rows}
    status = "PASS" if system_drive.casefold() in roots else "WARN"
    displays = [str(row.get("display") or row.get("root") or "") for row in rows]
    detail = f"{len(rows)} Laufwerk(e) erkannt: " + " | ".join(displays[:12])
    if len(displays) > 12:
        detail += f" | +{len(displays) - 12} weitere"
    if status != "PASS":
        detail = f"Systemlaufwerk {system_drive} fehlt im Inventar · " + detail
    return ("DRV-001", "Windows-Laufwerksinventar", status, detail[:1000])


def apply_drive_inventory_tuev_v1924(professional_module):
    """Prepend drive discovery to the existing filesystem/HiDrive TÜV checks."""
    if getattr(professional_module, "_drive_inventory_tuev_v1924", False):
        return

    original = professional_module.filesystem_tuev_checks

    def filesystem_tuev_checks(store, key_b64: str):
        return [drive_inventory_check(), *list(original(store, key_b64))]

    professional_module.filesystem_tuev_checks = filesystem_tuev_checks
    professional_module._drive_inventory_tuev_v1924 = True
