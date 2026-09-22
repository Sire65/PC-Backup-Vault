from __future__ import annotations

import os
import time

from object_store import make_b2_store
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



_B2_USAGE_CACHE_TTL_SECONDS = 15 * 60
_b2_usage_cache = {"key": None, "at": 0.0, "objectCount": None, "storedBytes": None, "newestObjectAt": None}


def _b2_usage(b2):
    """Cache the expensive full-prefix listing; ping remains live every cycle."""
    key = (str(getattr(b2, "bucket", "")), str(getattr(b2, "prefix", "")))
    now = time.monotonic()
    if (_b2_usage_cache["key"] == key
            and now - float(_b2_usage_cache["at"] or 0) < _B2_USAGE_CACHE_TTL_SECONDS):
        return _b2_usage_cache["objectCount"], _b2_usage_cache["storedBytes"], _b2_usage_cache["newestObjectAt"], True
    overview = b2.prefix_overview()
    count = int(overview.get("objectCount") or 0)
    stored = int(overview.get("storedBytes") or 0)
    newest = overview.get("newestObjectAt")
    _b2_usage_cache.update(key=key, at=now, objectCount=count, storedBytes=stored, newestObjectAt=newest)
    return count, stored, newest, False


def _b2_row(store) -> dict:
    checked_at = _now_iso()
    try:
        config = store.get_b2_runtime_config()
        b2 = make_b2_store(config)
    except Exception:
        b2 = None
    if b2 is None:
        return {
            "id": "b2_backup",
            "name": "Backblaze B2",
            "kind": "b2",
            "status": "not_configured",
            "latencyMs": None,
            "checkedAt": checked_at,
            "detail": "B2-Ziel nicht vollständig konfiguriert",
        }

    started = time.monotonic()
    ok, _detail = b2.ping()
    latency = int((time.monotonic() - started) * 1000)
    object_count = None
    stored_bytes = None
    usage_cached = None
    newest_object_at = None
    if ok:
        try:
            object_count, stored_bytes, newest_object_at, usage_cached = _b2_usage(b2)
        except Exception:
            # Reachability remains a separate signal; usage is optional and
            # must never turn a successful read-only ping into a false outage.
            pass
    return {
        "id": "b2_backup",
        "name": "Backblaze B2",
        "kind": "b2",
        "status": "healthy" if ok else "critical",
        "latencyMs": latency,
        "checkedAt": _now_iso(),
        "detail": "B2-Ziel erreichbar" if ok else "B2-Ziel nicht erreichbar",
        "objectCount": object_count,
        "storedBytes": stored_bytes,
        "newestObjectAt": newest_object_at,
        "usageCached": usage_cached,
        "usageCacheTtlSeconds": _B2_USAGE_CACHE_TTL_SECONDS,
    }


def _kc_archive_db_row(store) -> dict:
    """Prepared archive-database slot. No network call until explicitly configured."""
    cfg = dict(store.data.get("kc_archive_database") or {})
    enabled = bool(cfg.get("enabled"))
    provider = str(cfg.get("provider") or "pending").strip().lower()
    if not enabled:
        return {
            "id": "kc_archive_db",
            "name": "KC Archiv-Datenbank",
            "kind": "database_archive",
            "status": "not_configured",
            "latencyMs": None,
            "checkedAt": _now_iso(),
            "detail": "Vorbereitet; Anbieter/Zugang noch nicht freigegeben",
            "provider": provider,
        }
    # Credentials/DSNs are deliberately never emitted by storage telemetry.
    return {
        "id": "kc_archive_db",
        "name": "KC Archiv-Datenbank",
        "kind": "database_archive",
        "status": "unknown",
        "latencyMs": None,
        "checkedAt": _now_iso(),
        "detail": "Konfiguriert; aktive Nur-Lese-Pruefung wird erst nach Zugangsdaten freigegeben",
        "provider": provider,
    }


def collect_storage_health(store) -> list[dict]:
    """Return read-only, privacy-safe storage health for KC System Check.

    This production patch deliberately stays independent from the unreleased
    HiDrive transport module. It reports NAS reachability and configuration
    state for two HiDrive slots without exposing credentials, usernames,
    endpoints, roots or local/UNC paths.
    """
    return [_nas_row(store), _b2_row(store), _kc_archive_db_row(store), *_hidrive_rows(store)]
