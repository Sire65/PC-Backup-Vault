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

def install_task(plan: dict) -> tuple[bool,str]:
    if os.name != "nt": return False, "Windows Task Scheduler ist nur unter Windows verfügbar."
    kind = plan.get("schedule_type", "MANUAL")
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
    cp = subprocess.run(args, capture_output=True, text=True, creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    msg = (cp.stdout or cp.stderr or "").strip()
    return cp.returncode == 0, msg or ("Aufgabe angelegt." if cp.returncode == 0 else "Aufgabe konnte nicht angelegt werden.")

def remove_task(plan: dict) -> tuple[bool,str]:
    if os.name != "nt": return False, "Windows Task Scheduler ist nur unter Windows verfügbar."
    cp = subprocess.run(["schtasks","/Delete","/TN",_task_name(plan),"/F"], capture_output=True, text=True, creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    msg = (cp.stdout or cp.stderr or "").strip()
    return cp.returncode == 0, msg or ("Aufgabe entfernt." if cp.returncode == 0 else "Aufgabe nicht gefunden/entfernbar.")

def run_task_now(plan: dict) -> tuple[bool,str]:
    if os.name != "nt": return False, "Windows Task Scheduler ist nur unter Windows verfügbar."
    cp = subprocess.run(["schtasks","/Run","/TN",_task_name(plan)], capture_output=True, text=True, creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    msg = (cp.stdout or cp.stderr or "").strip()
    return cp.returncode == 0, msg

def task_status(plan: dict) -> tuple[bool, str]:
    """Read-only status check for a configured Windows task."""
    if os.name != "nt":
        return False, "Windows Task Scheduler ist nur unter Windows verfügbar."
    cp = subprocess.run(
        ["schtasks", "/Query", "/TN", _task_name(plan), "/FO", "LIST", "/V"],
        capture_output=True, text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
    )
    msg = (cp.stdout or cp.stderr or "").strip()
    return cp.returncode == 0, msg[:2000] or ("Scheduler-Aufgabe vorhanden." if cp.returncode == 0 else "Scheduler-Aufgabe nicht gefunden.")
