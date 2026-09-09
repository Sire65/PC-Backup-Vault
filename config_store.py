import json, os, uuid
from pathlib import Path
import keyring

APP_NAME = "PCBackupVault"
SERVICE = "PC Backup Vault"
APP_VERSION = "1.9.13"


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
            "b2": {"enabled": False, "key_id": "", "bucket_name": "", "endpoint": "", "upload_workers": 4},
            "system_image": {"enabled": False, "last_target": "", "last_run": None},
            "kc_communication": {"enabled": False, "endpoint_url": "", "device_id": "", "channels": []},
            "filesystem_targets": [],
            "active_filesystem_target_id": None,
            "cloud_accounts": [],
        }
        self._load()
        self.data["app_version"] = APP_VERSION

    def _load(self):
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    self.data.update(raw)
            except Exception:
                pass

    def save(self):
        self.data["app_version"] = APP_VERSION
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    def get_master_key(self):
        try:
            return keyring.get_password(SERVICE, "master_key")
        except Exception:
            return None

    def set_master_key(self, key):
        keyring.set_password(SERVICE, "master_key", key)

    def get_profile(self):
        pid = self.data.get("active_profile_id")
        return next((p for p in self.data.get("profiles", []) if p.get("id") == pid), None)

    def set_profile(self, profile):
        profiles = self.data.setdefault("profiles", [])
        existing = next((p for p in profiles if p.get("id") == profile.get("id")), None)
        if existing is None:
            profiles.append(profile)
        else:
            existing.clear(); existing.update(profile)
        self.data["active_profile_id"] = profile.get("id")
        self.save()

    def get_dsn(self, profile_id):
        try:
            return keyring.get_password(SERVICE, f"dsn:{profile_id}")
        except Exception:
            return None

    def set_dsn(self, profile_id, dsn):
        keyring.set_password(SERVICE, f"dsn:{profile_id}", dsn)

    def get_b2_runtime_config(self):
        cfg = dict(self.data.get("b2") or {})
        try:
            app_key = keyring.get_password(SERVICE, "b2_application_key")
        except Exception:
            app_key = None
        cfg["application_key"] = app_key or ""
        cfg["configured"] = bool(cfg.get("enabled") and cfg.get("key_id") and cfg.get("application_key") and cfg.get("bucket_name"))
        return cfg

    def set_b2_secret(self, application_key):
        keyring.set_password(SERVICE, "b2_application_key", application_key)

    def get_plan(self, plan_id):
        return next((p for p in self.data.get("plans", []) if str(p.get("id")) == str(plan_id)), None)

    def add_plan(self, plan):
        item = dict(plan or {})
        item.setdefault("id", str(uuid.uuid4()))
        self.data.setdefault("plans", []).append(item)
        if not self.data.get("default_plan_id"):
            self.data["default_plan_id"] = item["id"]
        self.save()
        return item["id"]

    def update_plan(self, plan_id, patch):
        plan = self.get_plan(plan_id)
        if not plan:
            return None
        plan.update(dict(patch or {}))
        self.save()
        return plan_id

    def delete_plan(self, plan_id):
        before = len(self.data.get("plans", []))
        self.data["plans"] = [p for p in self.data.get("plans", []) if str(p.get("id")) != str(plan_id)]
        if str(self.data.get("default_plan_id")) == str(plan_id):
            self.data["default_plan_id"] = self.data["plans"][0]["id"] if self.data["plans"] else None
        if len(self.data["plans"]) != before:
            self.save()
            return True
        return False

    def set_default_plan(self, plan_id):
        self.data["default_plan_id"] = plan_id
        self.save()

    def get_default_plan(self):
        return self.get_plan(self.data.get("default_plan_id"))

    def get_cloud_secret(self, account_id, field):
        try:
            return keyring.get_password(SERVICE, f"cloud:{account_id}:{field}")
        except Exception:
            return None

    def set_cloud_secret(self, account_id, field, value):
        keyring.set_password(SERVICE, f"cloud:{account_id}:{field}", value)
