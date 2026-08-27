from __future__ import annotations

import json
import threading
import time
import urllib.request
from datetime import datetime, timezone

from config_store import APP_VERSION
from status_bus import subscribe
from vault_db import recent_jobs, recent_restore_tests, recent_verifications

TELEMETRY_ENDPOINT = "https://ptblnpiroqftcvlsrhac.supabase.co/functions/v1/kc-backup-telemetry-machine"
SOURCE_PROGRAM = "pc-backup-vault"


def _iso(value):
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    try:
        return datetime.fromisoformat(str(value)).isoformat()
    except Exception:
        return None


def _safe_status(value, allowed, fallback="UNKNOWN"):
    text = str(value or "").upper()
    return text if text in allowed else fallback


def _latest_snapshot(dsn: str) -> dict:
    jobs = list(recent_jobs(dsn, 20) or [])
    verifies = list(recent_verifications(dsn, 20) or [])
    restores = list(recent_restore_tests(dsn, 20) or [])

    job = jobs[0] if jobs else None
    verify = verifies[0] if verifies else None
    restore = restores[0] if restores else None

    last_backup_at = _iso(job[2] if job and len(job) > 2 else None) or _iso(job[1] if job and len(job) > 1 else None)
    backup_status = _safe_status(job[3] if job and len(job) > 3 else None,
                                 {"SUCCESS", "FAILED", "PARTIAL", "CANCELLED", "INTERRUPTED", "RUNNING", "BLOCKED_LIMIT"})
    verify_result = _safe_status(verify[5] if verify and len(verify) > 5 else None, {"PASS", "WARN", "FAIL"})
    restore_result = _safe_status(restore[1] if restore and len(restore) > 1 else None, {"PASS", "WARN", "FAIL", "SUCCESS", "FAILED"})

    if backup_status in {"FAILED", "INTERRUPTED", "BLOCKED_LIMIT"} or verify_result == "FAIL" or restore_result in {"FAIL", "FAILED"}:
        status = "FAILED"
    elif backup_status in {"PARTIAL", "CANCELLED", "RUNNING"} or verify_result in {"WARN", "UNKNOWN"}:
        status = "DEGRADED"
    elif backup_status == "SUCCESS" and verify_result == "PASS":
        status = "HEALTHY"
    else:
        status = "UNKNOWN"

    rpo_seconds = None
    if last_backup_at:
        try:
            dt = datetime.fromisoformat(last_backup_at.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            rpo_seconds = max(0, int((datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds()))
        except Exception:
            pass

    return {
        "sourceProgram": SOURCE_PROGRAM,
        "appVersion": APP_VERSION,
        "status": status,
        "measuredAt": datetime.now(timezone.utc).isoformat(),
        "lastBackupAt": last_backup_at,
        "lastBackupStatus": backup_status,
        "lastBackupBytes": int(job[6] or 0) if job and len(job) > 6 else None,
        "lastBackupFiles": int(job[4] or 0) if job and len(job) > 4 else None,
        "backupTarget": str(job[15] or "")[:40] if job and len(job) > 15 else None,
        "lastVerifyAt": _iso(verify[4] if verify and len(verify) > 4 else None),
        "lastVerifyResult": verify_result,
        "lastRestoreTestAt": _iso(restore[0] if restore and len(restore) > 0 else None),
        "lastRestoreTestResult": restore_result,
        "integrityStatus": verify_result,
        "rpoSeconds": rpo_seconds,
        "rtoSeconds": None,
        "details": {
            "backupMode": str(job[11] or "")[:40] if job and len(job) > 11 else "",
            "triggerType": str(job[9] or "")[:40] if job and len(job) > 9 else "",
        },
    }


def _post(store, payload: dict) -> bool:
    cfg = dict(store.data.get("kc_communication") or {})
    if not cfg.get("enabled"):
        return False
    device_id = str(cfg.get("device_id") or "")
    token = store.get_kc_device_token() or ""
    if not device_id or len(token) < 32:
        return False
    payload = dict(payload)
    payload["deviceId"] = device_id
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        TELEMETRY_ENDPOINT,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": f"PCBackupVault/{APP_VERSION}",
            "x-pbv-device-token": token,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return 200 <= int(getattr(resp, "status", 200) or 200) < 300
    except Exception:
        return False


class BackupTelemetryReporter:
    def __init__(self, store, dsn_getter, interval_seconds: int = 60):
        self.store = store
        self.dsn_getter = dsn_getter
        self.interval = max(30, int(interval_seconds or 60))
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._unsubscribe = subscribe(self._on_status)
        self._thread = threading.Thread(target=self._run, name="kicc-backup-telemetry", daemon=True)
        self._thread.start()

    def _on_status(self, service: str, event: str, payload: dict):
        if str(service).lower() in {"neon", "b2", "verify", "vault", "kc"}:
            self._wake.set()

    def send_now(self):
        try:
            dsn = self.dsn_getter()
            if not dsn:
                return False
            return _post(self.store, _latest_snapshot(dsn))
        except Exception:
            return False

    def _run(self):
        time.sleep(4)
        while not self._stop.is_set():
            self.send_now()
            self._wake.clear()
            self._wake.wait(self.interval)

    def stop(self):
        self._stop.set()
        self._wake.set()
        try:
            self._unsubscribe()
        except Exception:
            pass


def start_backup_telemetry(store, dsn_getter):
    return BackupTelemetryReporter(store, dsn_getter)
