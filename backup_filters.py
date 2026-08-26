from __future__ import annotations
from datetime import datetime, date, time, timedelta

TIME_PRESETS = [
    "Heute",
    "Diese Woche",
    "Letzte Woche",
    "Letzte 7 Tage",
    "Letzte 30 Tage",
    "Dieser Monat",
    "Letzter Monat",
    "Dieses Quartal",
    "Letztes Quartal",
    "Dieses Jahr",
    "Letztes Jahr",
    "Alle",
    "Benutzerdefiniert",
]

STATUS_OPTIONS = {
    "Alle": None,
    "Erfolgreich": {"SUCCESS"},
    "Teilweise / Warnung": {"PARTIAL"},
    "Fehler": {"FAILED", "BLOCKED_LIMIT"},
    "Abgebrochen": {"CANCELLED"},
    "Unterbrochen / fortsetzbar": {"INTERRUPTED"},
    "Laufend": {"RUNNING"},
}

MODE_OPTIONS = {
    "Alle": None,
    "Automatisch": {"AUTO"},
    "Vollständig": {"FULL"},
    "Inkrementell": {"INCREMENTAL"},
    "Schnell": {"QUICK"},
}

STORAGE_OPTIONS = {
    "Alle": None,
    "Backblaze B2": {"B2"},
    "Neon": {"NEON"},
}

VERIFY_OPTIONS = {
    "Alle": None,
    "Bestanden": {"PASS"},
    "Warnung": {"WARN"},
    "Fehler": {"FAIL"},
    "Nicht verifiziert": {None},
}

PROBLEM_STATUSES = {"FAILED", "PARTIAL", "BLOCKED_LIMIT", "CANCELLED", "INTERRUPTED"}
GERMAN_MONTHS = ["", "Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"]


def parse_german_date(value: str) -> date:
    return datetime.strptime((value or "").strip(), "%d.%m.%Y").date()


def _aware_midnight(d: date, tzinfo):
    return datetime.combine(d, time.min, tzinfo=tzinfo)


def period_bounds(preset: str, reference: datetime, custom_from: str = "", custom_to: str = ""):
    """Return (start inclusive, end exclusive, caption)."""
    tz = reference.tzinfo
    today = reference.date()
    preset = preset or "Dieser Monat"

    if preset == "Alle":
        return None, None, "Alle Sicherungen"
    if preset == "Heute":
        start_d = today
        end_d = today + timedelta(days=1)
        caption = today.strftime("%d.%m.%Y")
    elif preset == "Diese Woche":
        start_d = today - timedelta(days=today.weekday())
        end_d = start_d + timedelta(days=7)
        caption = f"KW {today.isocalendar().week} · {start_d:%d.%m.} – {(end_d-timedelta(days=1)):%d.%m.%Y}"
    elif preset == "Letzte Woche":
        this_week = today - timedelta(days=today.weekday())
        start_d = this_week - timedelta(days=7)
        end_d = this_week
        caption = f"KW {start_d.isocalendar().week} · {start_d:%d.%m.} – {(end_d-timedelta(days=1)):%d.%m.%Y}"
    elif preset == "Letzte 7 Tage":
        start_d = today - timedelta(days=6)
        end_d = today + timedelta(days=1)
        caption = f"{start_d:%d.%m.%Y} – {today:%d.%m.%Y}"
    elif preset == "Letzte 30 Tage":
        start_d = today - timedelta(days=29)
        end_d = today + timedelta(days=1)
        caption = f"{start_d:%d.%m.%Y} – {today:%d.%m.%Y}"
    elif preset == "Dieser Monat":
        start_d = today.replace(day=1)
        if start_d.month == 12:
            end_d = date(start_d.year + 1, 1, 1)
        else:
            end_d = date(start_d.year, start_d.month + 1, 1)
        caption = f"{GERMAN_MONTHS[start_d.month]} {start_d.year}"
    elif preset == "Letzter Monat":
        this_month = today.replace(day=1)
        last_day_prev = this_month - timedelta(days=1)
        start_d = last_day_prev.replace(day=1)
        end_d = this_month
        caption = f"{GERMAN_MONTHS[start_d.month]} {start_d.year}"
    elif preset in ("Dieses Quartal", "Letztes Quartal"):
        q = (today.month - 1) // 3 + 1
        year = today.year
        if preset == "Letztes Quartal":
            q -= 1
            if q == 0:
                q = 4
                year -= 1
        start_month = 1 + (q - 1) * 3
        start_d = date(year, start_month, 1)
        if q == 4:
            end_d = date(year + 1, 1, 1)
        else:
            end_d = date(year, start_month + 3, 1)
        caption = f"Q{q} {year}"
    elif preset in ("Dieses Jahr", "Letztes Jahr"):
        year = today.year if preset == "Dieses Jahr" else today.year - 1
        start_d = date(year, 1, 1)
        end_d = date(year + 1, 1, 1)
        caption = str(year)
    elif preset == "Benutzerdefiniert":
        start_d = parse_german_date(custom_from)
        end_inclusive = parse_german_date(custom_to)
        if end_inclusive < start_d:
            raise ValueError("Das Bis-Datum liegt vor dem Von-Datum.")
        end_d = end_inclusive + timedelta(days=1)
        caption = f"{start_d:%d.%m.%Y} – {end_inclusive:%d.%m.%Y}"
    else:
        raise ValueError(f"Unbekannter Zeitraum: {preset}")

    return _aware_midnight(start_d, tz), _aware_midnight(end_d, tz), caption


def status_display(code: str) -> str:
    return {
        "SUCCESS": "Erfolgreich",
        "PARTIAL": "Teilweise",
        "FAILED": "Fehler",
        "CANCELLED": "Abgebrochen",
        "INTERRUPTED": "Unterbrochen",
        "BLOCKED_LIMIT": "Limit blockiert",
        "RUNNING": "Laufend",
    }.get(code or "", code or "–")


def mode_display(code: str) -> str:
    return {
        "AUTO": "Automatisch",
        "FULL": "Vollständig",
        "INCREMENTAL": "Inkrementell",
        "QUICK": "Schnell",
    }.get(code or "", code or "–")
