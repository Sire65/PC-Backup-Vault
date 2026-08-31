from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UserGuidance:
    title: str
    message: str
    action: str
    severity: str = "info"


def guidance_for_task(task_id: str) -> UserGuidance:
    key = str(task_id or "").strip().lower()
    mapping = {
        "secure": UserGuidance("Jetzt sichern", "Wählen Sie aus, was gesichert werden soll. Das Programm prüft Ziel und Voraussetzungen vor dem Start.", "Sicherung vorbereiten"),
        "check_disk": UserGuidance("Festplatte prüfen", "Die Prüfung arbeitet zuerst nur lesend. Bei auffälligen Datenträgern wird keine Reparatur automatisch gestartet.", "Datenträger erkennen"),
        "recover": UserGuidance("Daten retten", "Zuerst Zustand prüfen, dann ein vollständiges Image erstellen. Analyse und Recovery arbeiten anschließend mit dem Image.", "Recovery-Assistent öffnen", "warning"),
        "restore": UserGuidance("Backup zurückholen", "Wählen Sie eine Sicherung aus. Vor dem Zurückspielen wird deren Zustand geprüft.", "Sicherung auswählen"),
        "projects": UserGuidance("Projekte ordnen", "Project Finder sucht, klassifiziert und bereitet Projekte vor. Eine Git-Übertragung erfolgt nicht automatisch.", "Projekte suchen"),
        "system": UserGuidance("System prüfen", "Der TÜV prüft Programmzustand, wichtige Verbindungen und Sicherheitsregeln.", "TÜV starten"),
    }
    return mapping.get(key, UserGuidance("Aufgabe", "Für diese Aufgabe liegt noch keine geführte Beschreibung vor.", "Bereich öffnen"))


def friendly_error(exc: Exception) -> str:
    text = str(exc or "").strip()
    low = text.lower()
    if "physicaldrive" in low or "physisch" in low:
        return "Der gewählte Datenträger ist aus Sicherheitsgründen nicht zulässig. Bitte ein eindeutig separates Ziel wählen."
    if "image" in low and ("größer" in low or "complete" in low or "abgeschlossen" in low):
        return "Das Image ist noch nicht eindeutig vollständig. Recovery bleibt deshalb gesperrt."
    if "password" in low or "passwort" in low or "auth" in low:
        return "Anmeldung nicht möglich. Zugangsdaten prüfen; das Passwort wird nicht im Fehlertext gespeichert."
    if "timeout" in low or "zeitüberschreitung" in low:
        return "Die Aktion hat zu lange gedauert. Verbindung bzw. Datenträger prüfen und erneut versuchen."
    return text or "Die Aktion konnte nicht abgeschlossen werden. Details stehen im Diagnose-/TÜV-Bereich."
