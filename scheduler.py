from __future__ import annotations
import os, re, subprocess, sys
from pathlib import Path

PREFIX = "PC Backup Vault - "
WEEKDAYS = {"MON":"MON","TUE":"TUE","WED":"WED","THU":"THU","FRI":"FRI","SAT":"SAT","SUN":"SUN"}

def _task_name(plan: dict) -> str:
    safe = re.sub(r"[^A-Za-z0-9 äöüÄÖÜß._-]+", "_", plan.get("name") or "Backup").strip()
    return (PREFIX + safe + " - " + plan["id"][:8])[:220]

def _runner_command(plan_id: str) -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --run-plan "{plan_id}"'
    app = Path(__file__).with_name("app.py")
    py = Path(sys.executable)
    pyw = py.with_name("pythonw.exe") if os.name == "nt" and py.with_name("pythonw.exe").exists() else py
    return f'"{pyw}" "{app}" --run-plan "{plan_id}"'

def _run(args):
    return subprocess.run(args, capture_output=True, text=True, creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))

def install_task(plan: dict) -> tuple[bool,str]:
    if os.name != "nt": return False, "Windows Task Scheduler ist nur unter Windows verfügbar."
    kind = str(plan.get("schedule_type", "MANUAL") or "MANUAL").upper()
    if kind == "MANUAL": return False, "Plan steht auf Manuell."
    task = _task_name(plan)
    args = ["schtasks", "/Create", "/TN", task, "/TR", _runner_command(plan["id"]), "/F", "/RL", "LIMITED", "/IT"]
    if kind == "DAILY":
        args += ["/SC", "DAILY", "/ST", plan.get("schedule_time", "20:00")]
    elif kind == "WEEKLY":
        args += ["/SC", "WEEKLY", "/D", WEEKDAYS.get(plan.get("weekday","MON"),"MON"), "/ST", plan.get("schedule_time", "20:00")]
    elif kind == "ONLOGON":
        args += ["/SC", "ONLOGON"]
    else:
        return False, f"Unbekannter Scheduler-Typ: {kind}"
    cp = _run(args)
    msg = (cp.stdout or cp.stderr or "").strip()
    return cp.returncode == 0, msg or ("Aufgabe angelegt." if cp.returncode == 0 else "Aufgabe konnte nicht angelegt werden.")

def remove_task(plan: dict) -> tuple[bool,str]:
    if os.name != "nt": return False, "Windows Task Scheduler ist nur unter Windows verfügbar."
    cp = _run(["schtasks","/Delete","/TN",_task_name(plan),"/F"])
    msg = (cp.stdout or cp.stderr or "").strip()
    return cp.returncode == 0, msg or ("Aufgabe entfernt." if cp.returncode == 0 else "Aufgabe nicht gefunden/entfernbar.")

def run_task_now(plan: dict) -> tuple[bool,str]:
    if os.name != "nt": return False, "Windows Task Scheduler ist nur unter Windows verfügbar."
    cp = _run(["schtasks","/Run","/TN",_task_name(plan)])
    msg = (cp.stdout or cp.stderr or "").strip()
    return cp.returncode == 0, msg

def task_status(plan: dict) -> tuple[bool, str]:
    """Read-only status check for a configured Windows task."""
    kind = str(plan.get("schedule_type", "MANUAL") or "MANUAL").upper()
    if kind == "MANUAL":
        return True, "Manueller Plan – keine Windows-Aufgabe erforderlich."
    if os.name != "nt":
        return False, "Windows Task Scheduler ist nur unter Windows verfügbar."
    cp = _run(["schtasks", "/Query", "/TN", _task_name(plan), "/FO", "LIST", "/V"])
    msg = (cp.stdout or cp.stderr or "").strip()
    return cp.returncode == 0, msg[:2000] or ("Scheduler-Aufgabe vorhanden." if cp.returncode == 0 else "Scheduler-Aufgabe nicht gefunden.")

def task_diagnostic(plan: dict) -> tuple[str, str]:
    """Read-only release diagnostic for one backup plan.

    Returns PASS/WARN/FAIL plus a concise explanation. Manual plans are PASS because
    they intentionally do not require a Windows scheduled task.
    """
    kind = str(plan.get("schedule_type", "MANUAL") or "MANUAL").upper()
    name = str(plan.get("name") or "Backup-Plan")
    if kind == "MANUAL":
        return "PASS", f"{name}: Manuell – keine Windows-Aufgabe erforderlich"
    ok, msg = task_status(plan)
    if not ok:
        return "WARN", f"{name}: Windows-Aufgabe fehlt oder ist nicht lesbar – {(msg or '').splitlines()[0]}"
    expected = _runner_command(plan["id"])
    cp = _run(["schtasks", "/Query", "/TN", _task_name(plan), "/XML"])
    xml = cp.stdout or ""
    if cp.returncode != 0:
        return "WARN", f"{name}: Aufgabe vorhanden, Details konnten nicht gelesen werden"
    # Detect stale source/Python paths after switching from STARTEN.bat/source mode to installed EXE.
    expected_exe = str(sys.executable)
    if getattr(sys, "frozen", False):
        if expected_exe.lower() not in xml.lower():
            return "WARN", f"{name}: Aufgabe verweist auf einen alten Programm-Pfad"
    elif str(Path(__file__).with_name("app.py")).lower() not in xml.lower():
        return "WARN", f"{name}: Aufgabe verweist nicht auf den aktuellen Quellstand"
    return "PASS", f"{name}: Windows-Aufgabe vorhanden und Programm-Pfad aktuell"

def sync_all_tasks(store) -> list[tuple[str,str,str]]:
    """Synchronize all auto-managed plans to the current executable/source path.

    This is intentionally conservative: only plans with scheduler_auto_sync enabled are
    changed. Scheduled plans are recreated with /F; manual plans have stale tasks removed.
    """
    results=[]
    for plan in list(store.data.get("plans", []) or []):
        if not bool(plan.get("scheduler_auto_sync", True)):
            results.append((plan.get("name") or "Backup-Plan", "SKIP", "Automatische Scheduler-Synchronisierung ausgeschaltet"))
            continue
        kind=str(plan.get("schedule_type", "MANUAL") or "MANUAL").upper()
        if kind == "MANUAL":
            # Best effort cleanup; absence of a task is the desired state.
            remove_task(plan)
            results.append((plan.get("name") or "Backup-Plan", "PASS", "Manuell – keine Windows-Aufgabe erforderlich"))
            continue
        ok,msg=install_task(plan)
        results.append((plan.get("name") or "Backup-Plan", "PASS" if ok else "WARN", msg))
    return results
