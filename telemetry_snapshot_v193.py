"""Read-only telemetry snapshot for KC System Check.

This module exposes operational metadata only. It must never return credentials,
recovery keys, decrypted file names/paths, or backup payloads.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Mapping, Optional


TELEMETRY_SCHEMA_VERSION = "1.0"
SENSITIVE_KEYS = {
    "password",
    "passwd",
    "secret",
    "token",
    "access_key",
    "access_key_id",
    "application_key",
    "api_key",
    "dsn",
    "recovery_key",
    "private_key",
    "original_path",
    "decrypted_path",
    "filename",
    "file_name",
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe(value: Any) -> Any:
    """Recursively strip keys that must never leave Backup Vault."""
    if isinstance(value, Mapping):
        cleaned: Dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text.lower() in SENSITIVE_KEYS:
                continue
            cleaned[key_text] = _safe(item)
        return cleaned
    if isinstance(value, (list, tuple, set)):
        return [_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _normalise_status(value: Optional[str]) -> str:
    status = (value or "unknown").strip().lower()
    aliases = {
        "ok": "healthy",
        "success": "healthy",
        "successful": "healthy",
        "warn": "warning",
        "failed": "critical",
        "error": "critical",
        "offline": "critical",
        "not_configured": "not_configured",
        "disabled": "not_configured",
    }
    status = aliases.get(status, status)
    if status not in {"healthy", "warning", "critical", "unknown", "not_configured"}:
        return "unknown"
    return status


def build_snapshot(
    *,
    app_version: str,
    vault_status: str = "unknown",
    last_job: Optional[Mapping[str, Any]] = None,
    targets: Optional[Iterable[Mapping[str, Any]]] = None,
    last_verify: Optional[Mapping[str, Any]] = None,
    last_restore_test: Optional[Mapping[str, Any]] = None,
    capacity: Optional[Mapping[str, Any]] = None,
    generated_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the stable, read-only payload consumed by KC System Check.

    Callers are expected to pass already-aggregated metadata. `_safe` provides a
    final fail-closed redaction layer before serialization.
    """
    payload = {
        "schemaVersion": TELEMETRY_SCHEMA_VERSION,
        "sourceProgram": "pc-backup-vault",
        "generatedAt": generated_at or _utc_now_iso(),
        "appVersion": str(app_version),
        "status": _normalise_status(vault_status),
        "lastJob": dict(last_job or {}),
        "targets": [dict(item) for item in (targets or [])],
        "lastVerify": dict(last_verify or {}),
        "lastRestoreTest": dict(last_restore_test or {}),
        "capacity": dict(capacity or {}),
    }
    return _safe(payload)


def system_check_view(snapshot: Mapping[str, Any]) -> Dict[str, Any]:
    """Return KC System Check's common check-record shape.

    This deliberately contains summary telemetry only; the complete read-only
    snapshot can be retained locally by the bridge for diagnostics.
    """
    safe_snapshot = _safe(snapshot)
    targets = safe_snapshot.get("targets") or []
    failing = [t for t in targets if _normalise_status(str(t.get("status", "unknown"))) == "critical"]
    warnings = [t for t in targets if _normalise_status(str(t.get("status", "unknown"))) == "warning"]
    status = _normalise_status(str(safe_snapshot.get("status", "unknown")))
    if failing:
        status = "critical"
    elif warnings and status == "healthy":
        status = "warning"

    detail = "Backup Vault Telemetrie verfügbar"
    if failing:
        detail = f"{len(failing)} Speicherziel(e) kritisch"
    elif warnings:
        detail = f"{len(warnings)} Speicherziel(e) mit Warnung"

    return {
        "id": "backup_vault",
        "name": "PC Backup Vault",
        "kind": "backup",
        "status": status,
        "health": status,
        "latency": None,
        "usage": safe_snapshot.get("capacity", {}).get("usage"),
        "capacityLabel": safe_snapshot.get("capacity", {}).get("label"),
        "detail": detail,
        "metrics": {
            "generatedAt": safe_snapshot.get("generatedAt"),
            "lastJob": safe_snapshot.get("lastJob", {}),
            "lastVerify": safe_snapshot.get("lastVerify", {}),
            "lastRestoreTest": safe_snapshot.get("lastRestoreTest", {}),
            "targets": targets,
        },
    }
