from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Callable

from hidrive_sftp_v192 import _root, sftp_connection


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_detail(text: object, limit: int = 180) -> str:
    value = str(text or "").replace("\r", " ").replace("\n", " ")
    # Telemetry must not disclose Windows/UNC paths or credentials.
    if ":\\" in value or value.startswith("\\\\"):
        return "Zielprüfung fehlgeschlagen. Details nur lokal in Backup Vault anzeigen."
    return value[:limit]


def _nas_rows(store) -> list[dict]:
    rows = []
    for target in list(store.data.get("filesystem_targets") or []):
        if str(target.get("kind") or "").upper() != "NAS":
            continue
        started = time.monotonic()
        path = str(target.get("path") or "").strip()
        reachable = bool(path) and os.path.isdir(path)
        rows.append({
            "id": "nas_backup",
            "name": str(target.get("name") or "NAS Backup")[:80],
            "kind": "nas",
            "status": "healthy" if reachable else "critical",
            "latencyMs": int((time.monotonic() - started) * 1000),
            "checkedAt": _now_iso(),
            "detail": "NAS-Ziel erreichbar" if reachable else "NAS-Ziel nicht erreichbar",
        })
    if not rows:
        rows.append({
            "id": "nas_backup",
            "name": "NAS Backup",
            "kind": "nas",
            "status": "not_configured",
            "latencyMs": None,
            "checkedAt": _now_iso(),
            "detail": "Kein NAS-Ziel konfiguriert",
        })
    return rows[:1]


def _hidrive_probe(store, account_id: str) -> tuple[bool, int, str]:
    started = time.monotonic()
    try:
        with sftp_connection(store, account_id) as (sftp, account):
            # Read-only liveness check: authenticate and stat the configured root.
            sftp.stat(_root(account))
        return True, int((time.monotonic() - started) * 1000), "HiDrive SFTP erreichbar"
    except Exception as exc:
        return False, int((time.monotonic() - started) * 1000), _safe_detail(exc)


def _configured_hidrive_accounts(store) -> list[dict]:
    """Read configured accounts without normalising or mutating the store.

    Telemetry collection must be observational only. In particular it must not
    call cloud_targets_v191.cloud_accounts(), because that helper may persist
    missing defaults as part of normal UI initialisation.
    """
    return [
        dict(a) for a in list(store.data.get("cloud_accounts") or [])
        if str(a.get("provider_code") or "").upper() == "STRATO_HIDRIVE" and a.get("enabled", True)
    ]


def _hidrive_rows(store, probe: Callable[[object, str], tuple[bool, int, str]] | None = None) -> list[dict]:
    probe = probe or _hidrive_probe
    accounts = _configured_hidrive_accounts(store)
    rows = []
    for index, account in enumerate(accounts[:2], start=1):
        ok, latency, detail = probe(store, str(account.get("id") or ""))
        rows.append({
            "id": f"hidrive_{index}",
            "name": str(account.get("name") or f"HiDrive {index}")[:80],
            "kind": "hidrive",
            "status": "healthy" if ok else "critical",
            "latencyMs": latency,
            "checkedAt": _now_iso(),
            "detail": "HiDrive erreichbar" if ok else _safe_detail(detail),
        })
    while len(rows) < 2:
        index = len(rows) + 1
        rows.append({
            "id": f"hidrive_{index}",
            "name": f"HiDrive {index}",
            "kind": "hidrive",
            "status": "not_configured",
            "latencyMs": None,
            "checkedAt": _now_iso(),
            "detail": "HiDrive-Konto nicht konfiguriert",
        })
    return rows


def collect_storage_health(store, hidrive_probe=None) -> list[dict]:
    """Return read-only operational status for KC System Check.

    No password, username, endpoint, remote root or local/UNC path is emitted.
    HiDrive checks authenticate and stat only; they never create test files and
    this collector never modifies the Backup Vault configuration.
    """
    return [*_nas_rows(store), *_hidrive_rows(store, hidrive_probe)]
