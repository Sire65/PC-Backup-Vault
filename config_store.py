from __future__ import annotations
import json, os, uuid
from pathlib import Path
import keyring

APP_NAME = "PCBackupVault"
SERVICE = "PC Backup Vault"
APP_VERSION = "1.8.1"


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
        self.data.setdefault("auto_quick_verify_after_backup", True)
        self.data.setdefault("start_protocol_enabled", True)
        self.data.setdefault("auto_resume_interrupted", False)
        self.data.setdefault("last_scheduler_sync", None)
        self.data.setdefault("kc_communication", {})
        kc = self.data["kc_communication"]
        kc.setdefault("enabled", False)
        kc.setdefault("endpoint_url", "https://ptblnpiroqftcvlsrhac.supabase.co/functions/v1/kc-communication-machine")
        kc.setdefault("device_id", str(uuid.uuid4()))
        kc.setdefault("device_name", "PC Backup Vault")
        kc.setdefault("pairing_code", "")
        kc.setdefault("timeout_seconds", 8)
        kc.setdefault("channels", ["push", "email"])
        kc.setdefault("events", {})
        for event in (
            "backup_success", "backup_failed", "backup_cancelled", "backup_interrupted", "backup_resumed",
            "verify_failed", "restore_test_failed", "tuev_failed", "capacity_warning", "capacity_blocked",
            "scheduler_failed",
        ):
            kc["events"].setdefault(event, True)
        self.data.setdefault("b2", {})
        b2 = self.data["b2"]
        b2.setdefault("enabled", False)
        b2.setdefault("bucket", "")
        b2.setdefault("endpoint_url", "")
        b2.setdefault("region", "")
        b2.setdefault("prefix", "pc-backup-vault")
        b2.setdefault("soft_limit_gb", 8)
        b2.setdefault("hard_limit_gb", 10)
        b2.setdefault("upload_workers", 4)
        self.save()

    def load(self):
        if not self.path.exists():
            return
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                self.data.update(saved)
        except Exception:
            pass

    def save(self):
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    def get_profile(self, profile_id=None):
        pid = profile_id or self.data.get("active_profile_id")
        return next((p for p in self.data.get("profiles", []) if p.get("id") == pid), None)

    def add_profile(self, name, host, dbname, user, port=5432, sslmode="require"):
        item = {"id": str(uuid.uuid4()), "name": name, "host": host, "dbname": dbname, "user": user, "port": int(port), "sslmode": sslmode}
        self.data.setdefault("profiles", []).append(item)
        self.data["active_profile_id"] = item["id"]
        self.save()
        return item

    def get_dsn(self, profile_id):
        profile = self.get_profile(profile_id)
        if not profile:
            return None
        pwd = keyring.get_password(SERVICE, f"db:{profile_id}")
        if not pwd:
            return None
        return f"host={profile['host']} port={profile.get('port',5432)} dbname={profile['dbname']} user={profile['user']} password={pwd} sslmode={profile.get('sslmode','require')}"

    def set_db_password(self, profile_id, password):
        keyring.set_password(SERVICE, f"db:{profile_id}", password)

    def set_master_key(self, value):
        keyring.set_password(SERVICE, "master_key", value)

    def get_master_key(self):
        return keyring.get_password(SERVICE, "master_key")

    def set_b2_secret(self, key, value):
        keyring.set_password(SERVICE, f"b2:{key}", value)

    def get_b2_secret(self, key):
        return keyring.get_password(SERVICE, f"b2:{key}")

    def get_b2_runtime_config(self):
        cfg = dict(self.data.get("b2") or {})
        cfg["key_id"] = self.get_b2_secret("key_id") or ""
        cfg["application_key"] = self.get_b2_secret("application_key") or ""
        cfg["configured"] = bool(cfg.get("enabled") and cfg.get("bucket") and cfg.get("key_id") and cfg.get("application_key"))
        return cfg

    def set_kc_device_token(self, value):
        if value:
            keyring.set_password(SERVICE, "kc:device_token", value)
        else:
            try:
                keyring.delete_password(SERVICE, "kc:device_token")
            except Exception:
                pass

    def get_kc_device_token(self):
        return keyring.get_password(SERVICE, "kc:device_token")

    def get_plan(self, plan_id=None):
        pid = plan_id or self.data.get("default_plan_id")
        return next((p for p in self.data.get("plans", []) if p.get("id") == pid), None)
