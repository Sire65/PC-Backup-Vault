from __future__ import annotations

import ctypes
import ntpath
import os
import subprocess
from datetime import datetime
from pathlib import Path


def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _target_path(target: dict) -> str:
    p = str((target or {}).get("path") or "").strip()
    if not p:
        raise ValueError("Kein Ziel für das Systemabbild gewählt.")
    return p


def _windows_volume(path: str) -> str:
    """Return a Windows drive designator independent of the host OS.

    CI runs on Linux, where os.path.splitdrive("C:\\...") does not recognise
    the Windows drive. ntpath deliberately applies Windows path semantics on
    every platform, so the safety check is tested exactly like production.
    UNC paths intentionally return their share as the drive component.
    """
    return str(ntpath.splitdrive(str(path or ""))[0] or "").rstrip("\\/").upper()


def preflight_system_image(target: dict, include_volume: str | None = None) -> dict:
    path = _target_path(target)
    checks=[]
    exists = os.path.exists(path)
    checks.append(("Ziel erreichbar", exists, path))
    if exists:
        try:
            test = Path(path) / ".pbv-image-write-test"
            test.write_bytes(b"PBV"); test.unlink(missing_ok=True)
            checks.append(("Ziel beschreibbar", True, "Schreibtest OK"))
        except Exception as e:
            checks.append(("Ziel beschreibbar", False, str(e)))
    if include_volume:
        src = _windows_volume(include_volume)
        dst = _windows_volume(path)
        if src and dst and src == dst:
            checks.append(("Quelle/Ziel getrennt", False, "Systemabbild darf nicht auf demselben Volume liegen."))
        else:
            checks.append(("Quelle/Ziel getrennt", True, "OK"))
    checks.append(("Administratorrechte", _is_admin(), "Erforderlich für wbadmin"))
    return {"ok": all(ok for _,ok,_ in checks), "checks":[{"name":n,"ok":ok,"detail":d} for n,ok,d in checks]}


def create_system_image(target: dict, include_volume: str | None = None, quiet: bool = True) -> dict:
    """Create a Windows-native, WinRE-compatible bare-metal image.

    The WindowsImageBackup is deliberately NOT wrapped in PC Backup Vault AES.
    Native recoverability in Windows RE has priority. Protect the destination
    with BitLocker (external disk) or storage-side encryption (NAS) instead.
    """
    pre = preflight_system_image(target, include_volume)
    if not pre["ok"]:
        failures = [x["detail"] for x in pre["checks"] if not x["ok"]]
        raise RuntimeError("Systemabbild-Prüfung fehlgeschlagen:\n" + "\n".join(f"• {x}" for x in failures))
    backup_target = _target_path(target)
    cmd = ["wbadmin", "start", "backup", f"-backupTarget:{backup_target}", "-allCritical"]
    if include_volume:
        cmd.append(f"-include:{include_volume}")
    if quiet:
        cmd.append("-quiet")
    started = datetime.now().astimezone()
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    output = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    if proc.returncode != 0:
        raise RuntimeError(f"Windows-Systemabbild fehlgeschlagen (wbadmin {proc.returncode}).\n{output[-3000:]}")
    return {
        "status": "SUCCESS",
        "type": "SYSTEM_IMAGE",
        "started_at": started.isoformat(),
        "finished_at": datetime.now().astimezone().isoformat(),
        "target": backup_target,
        "include_volume": include_volume,
        "native_format": "WindowsImageBackup",
        "restore_environment": "Windows RE / wbadmin start sysrecovery",
        "application_encrypted": False,
        "encryption_note": "Für Bare-Metal-Restore Zielmedium mit BitLocker oder NAS-seitig schützen.",
    }


def recovery_instructions(target: str) -> str:
    return (
        "Bare-Metal-Wiederherstellung:\n"
        "1. Windows-Wiederherstellungsumgebung (WinRE) starten.\n"
        "2. Falls das Backup-Laufwerk mit BitLocker geschützt ist, mit dem Wiederherstellungsschlüssel entsperren.\n"
        "3. Systemimage-Wiederherstellung wählen oder in der Wiederherstellungskonsole 'wbadmin get versions' ausführen.\n"
        f"4. Backup-Ziel: {target}\n"
        "5. Gewünschten Stand auswählen und Systemwiederherstellung starten.\n"
        "Achtung: Bei Wiederherstellung auf andere Hardware können Treiber-/Lizenzanpassungen nötig sein."
    )
