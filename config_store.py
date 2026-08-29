from __future__ import annotations
import json, os, uuid
from pathlib import Path
import keyring

APP_NAME = "PCBackupVault"
SERVICE = "PC Backup Vault"
APP_VERSION = "1.8.0"


def _base_dir() -> Path:
    base = os.environ.get("APPDATA")
    p = (Path(base) / APP_NAME) if base else (Path.home() / f".{APP_NAME.lower()}")
    p.mkdir(parents=True, exist_ok=True)
    return p


class ConfigStore:
    def __init__(self):
        self.path = _base_dir() / "config.json"
        self.data = {
            "active_profile_id": None,
            "profiles": [],
            "plans": [],
            "default_plan_id": None,
            "christmas_guard": True,
            "max_run_mb": 100,
            "recovery_key_exported": False,
            "last_recovery_export": None,
            "app_version": APP_VERSION,
            "last_scheduler_sync": None,
            "dashboard_days": 30,
            "dashboard_period": "Dieser Monat",
            "retention_days": 90,
            "keep_last_versions": 10,
            "auto_delete_old_versions": False,
            "restore_selftest_after_backup": True,
            "restore_selftest_max_kb": 256,
            "payload_target_default": "AUTO",
            "auto_quick_verify_after_backup": True,
            "start_protocol_enabled": True,
            "auto_resume_interrupted": False,
            "kc_communication": {
                "enabled": False,
                "endpoint_url": "https://ptblnpiroqftcvlsrhac.supabase.co/functions/v1/kc-communication-machine",
                "device_id": str(uuid.uuid4()),
                "device_name": "PC Backup Vault",
                "pairing_code": "",
                "timeout_seconds": 8,
                "channels": ["push", "email"],
                "events": {
                    "backup_success": True, "backup_failed": True, "backup_cancelled": True,
                    "backup_interrupted": True, "backup_resumed": True, "verify_failed": True,
                    "restore_test_failed": True, "tuev_failed": True, "capacity_warning": True,
                    "capacity_blocked": True, "scheduler_failed": True,
                },
            },
            "b2": {
                "enabled": False,
                "bucket": "",
                "endpoint_url": "",
                "region": "",
                "prefix": "pc-backup-vault",
                "soft_limit_gb": 8,
                "hard_limit_gb": 10,
                "upload_workers": 4,
            },
        }
        self.load()
        self.data["app_version"] = APP_VERSION
        self.data.setdefault("plans", [])
        self.data.setdefault("default_plan_id", None)
        self.data.setdefault("dashboard_days", 30)
        self.data.setdefault("dashboard_period", "Dieser Monat")
        self.data.setdefault("retention_days", 90)
        self.data.setdefault("keep_last_versions", 10)
        self.data.setdefault("auto_delete_old_versions", False)
        self.data.setdefault("restore_selftest_after_backup", True)
        self.data.setdefault("restore_selftest_max_kb", 256)
        self.data.setdefault("payload_target_default", "AUTO")