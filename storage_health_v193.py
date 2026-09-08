from __future__ import annotations

import os
import time
from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_detail(text: object, limit: int = 180) -> str:
    value = str(text or "").replace("\r", " ").replace("\n", " ")
    lowered = value.lower()
    if ":\\" in value or value.startswith("\\\\") or "password" in lowered or "token" in lowered or "secret" in lowered:
        return "Zielpruefung fehlgeschlagen. Details nur lokal in Backup Vault anzeigen."
    return value[:limit]


def _nas_row(store) -> dict:
    targets = list(store.data.get("filesystem_targets") or [])
    nas = next((dict(t) for t in targets if str(t.get("kind") or "").upper() == "NAS"), None)
    if not nas:
        return {
            "id": "nas_backup",
            "name": "NAS Backup",
            "kind": "nas",
            "status": "not_configured",
            "latencyMs": None,
            "checkedAt": _now_iso(),
            "detail": "Kein NAS-Ziel konfiguriert",
        }

    started = time.monotonic()
    path = str(nas.get("path") or "").strip()
    reachable = bool(path) and os.path.isdir(path)
    return {
        "id": "nas_backup",
        "name": str(nas.get("name") or "NAS Backup")[:80],
        "kind": "nas",
        "status": "healthy" if reachable else "critical",
        "latencyMs": int((time.monotonic() - started) * 1000),
        "checkedAt": _now_iso(),
        "detail": "NAS-Ziel erreichbar" if reachable else "NAS-Ziel nicht erreichbar",
    }


def _hidrive_rows(store) -> list[dict]:
    accounts = [
        dict(a) for a in list(store.data.get("cloud_accounts") or [])
        if str(a.get("provider_code") or "").upper() == "STRATO_HIDRIVE" and a.get("enabled", True)
    ]
    rows = []
    for index in range(1, 3):
        account = accounts[index - 1] if len(accounts) >= index else None
        if not account:
            rows.append({
                "id": f"hidrive_{index}",
                "name": f"HiDrive {index}",
                "kind": "hidrive",
                "status": "not_configured",
                "latencyMs": None,
                "checkedAt": _now_iso(),
                "detail": "HiDrive-Konto nicht konfiguriert",
            })
            continue

        # The production telemetry patch must not import or activate the larger
        # HiDrive transport feature. Until that transport is released, a configured
        # account is reported as unknown rather than guessed healthy.
        rows.append({
            "id": f"hidrive_{index}",
            "name": str(account.get("name") or f"HiDrive {index}")[:80],
            "kind": "hidrive",
            "status": "unknown",
            "latencyMs": None,
            "checkedAt": _now_iso(),
            "detail": "Konfiguriert; aktive SFTP-Pruefung erst nach freigegebenem HiDrive-Modul",
        })
    return rows


def collect_storage_health(store) -> list[dict]:
    """Return read-only, privacy-safe storage health for KC System Check.

    This production patch deliberately stays independent from the unreleased
    HiDrive transport module. It reports NAS reachability and configuration
    state for two HiDrive slots without exposing credentials, usernames,
    endpoints, roots or local/UNC paths.
    """
    return [_nas_row(store), *_hidrive_rows(store)]
