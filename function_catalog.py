from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TaskEntry:
    task_id: str
    title: str
    question: str
    module_id: str
    detail: str
    advanced: bool = False


TASKS = (
    TaskEntry("secure", "Jetzt sichern", "Ich möchte Daten sichern", "backup", "Sicherung starten oder Sicherungsplan verwenden"),
    TaskEntry("check_disk", "Festplatte prüfen", "Eine Festplatte macht Probleme", "disk", "Datenträger erkennen, Zustand lesen und ohne Schreibzugriff prüfen"),
    TaskEntry("recover", "Daten retten", "Ich muss Daten von Platte/NAS retten", "nas", "Geführter Recovery-Ablauf: prüfen → Image → verifizieren → analysieren → retten"),
    TaskEntry("restore", "Backup zurückholen", "Ich möchte Dateien aus einer Sicherung wiederherstellen", "restore", "Sicherung auswählen, prüfen und kontrolliert wiederherstellen"),
    TaskEntry("projects", "Projekte ordnen", "Ich möchte Projekte finden, vergleichen oder für Git vorbereiten", "finder", "Project Finder, Dubletten, Hashes und Git-Vorbereitung"),
    TaskEntry("system", "System prüfen", "Ich möchte wissen, ob PC Backup Vault in Ordnung ist", "tuev", "TÜV, Diagnose, Logs und Systemzustand"),
    TaskEntry("cloud", "Cloud verwalten", "Ich möchte Cloud-Speicher oder Kosten prüfen", "cloud", "Provider, Freikontingente und Kostenschutz", True),
    TaskEntry("settings", "Einstellungen", "Ich möchte Ziele, Zugangsdaten oder Optionen ändern", "settings", "Programmkonfiguration und Zugangsdaten", True),
)


def visible_tasks(*, advanced: bool = False) -> tuple[TaskEntry, ...]:
    """Simple mode keeps technical functions out of the primary decision path."""
    return tuple(task for task in TASKS if advanced or not task.advanced)


def task_for_id(task_id: str) -> TaskEntry | None:
    key = str(task_id or "").strip().lower()
    return next((task for task in TASKS if task.task_id == key), None)
