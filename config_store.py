import json, os, uuid
from pathlib import Path
import keyring

APP_NAME = "PCBackupVault"
SERVICE = "PC Backup Vault"
APP_VERSION = "1.9.31"


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
