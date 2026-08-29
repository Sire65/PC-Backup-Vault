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
        self.data.setdefault("auto_quick_verify_after_backup", True)
        self.data.setdefault("start_protocol_enabled", True)
        self.data.setdefault("auto_resume_interrupted", False)
        kc = self.data.setdefault("kc_communication", {})
        kc.setdefault("enabled", False)
        kc.setdefault("endpoint_url", "https://ptblnpiroqftcvlsrhac.supabase.co/functions/v1/kc-communication-machine")
        kc.setdefault("device_id", str(uuid.uuid4()))
        kc.setdefault("device_name", "PC Backup Vault")
        kc.setdefault("pairing_code", "")
        kc.setdefault("timeout_seconds", 8)
        kc.setdefault("channels", ["push", "email"])
        events = kc.setdefault("events", {})
        for event_key in ("backup_success","backup_failed","backup_cancelled","backup_interrupted","backup_resumed",
                          "verify_failed","restore_test_failed","tuev_failed","capacity_warning","capacity_blocked","scheduler_failed"):
            events.setdefault(event_key, True)
        b2 = self.data.setdefault("b2", {})
        b2.setdefault("enabled", False)
        b2.setdefault("bucket", "")
        b2.setdefault("endpoint_url", "")
        b2.setdefault("region", "")
        b2.setdefault("prefix", "pc-backup-vault")
        b2.setdefault("soft_limit_gb", 8)
        b2.setdefault("hard_limit_gb", 10)
        b2.setdefault("upload_workers", 4)
        if not self.data["profiles"]:
            self.add_profile({
                "name": "Neon PC Backup Vault",
                "provider": "neon",
                "host_hint": "Neon / PC Backup Vault",
                "database": "pc_backup_vault",
                "project_ref": "restless-lake-98349332",
                "soft_limit_mb": 350,
                "hard_limit_mb": 420,
                "enabled": True,
            })
        self.save()

    def load(self):
        if self.path.exists():
            try:
                incoming = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(incoming, dict):
                    self.data.update(incoming)
            except Exception:
                pass

    def save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def add_profile(self, profile: dict) -> str:
        pid = profile.get("id") or str(uuid.uuid4())
        profile = dict(profile)
        profile["id"] = pid
        self.data["profiles"].append(profile)
        if not self.data.get("active_profile_id"):
            self.data["active_profile_id"] = pid
        self.save()
        return pid

    def update_profile(self, pid: str, values: dict):
        p = self.get_profile(pid)
        if not p:
            raise KeyError(pid)
        p.update(values)
        self.save()

    def delete_profile(self, pid: str):
        self.data["profiles"] = [p for p in self.data["profiles"] if p["id"] != pid]
        try:
            keyring.delete_password(SERVICE, f"dsn:{pid}")
        except Exception:
            pass
        if self.data.get("active_profile_id") == pid:
            self.data["active_profile_id"] = self.data["profiles"][0]["id"] if self.data["profiles"] else None
        for plan in self.data.get("plans", []):
            if plan.get("profile_id") == pid:
                plan["enabled"] = False
        self.save()

    def get_profile(self, pid: str | None = None) -> dict | None:
        pid = pid or self.data.get("active_profile_id")
        return next((p for p in self.data["profiles"] if p["id"] == pid), None)

    def set_active(self, pid: str):
        self.data["active_profile_id"] = pid
        self.save()

    def set_dsn(self, pid: str, dsn: str):
        if dsn.strip():
            keyring.set_password(SERVICE, f"dsn:{pid}", dsn.strip())

    def get_dsn(self, pid: str) -> str | None:
        return keyring.get_password(SERVICE, f"dsn:{pid}")

    def set_master_key(self, value: str):
        keyring.set_password(SERVICE, "master_key_v1", value)

    def get_master_key(self) -> str | None:
        return keyring.get_password(SERVICE, "master_key_v1")

    # Backblaze B2 credentials stay only in the OS credential store.
    def set_b2_credentials(self, access_key_id: str, application_key: str):
        if access_key_id.strip():
            keyring.set_password(SERVICE, "b2_access_key_id", access_key_id.strip())
        if application_key.strip():
            keyring.set_password(SERVICE, "b2_application_key", application_key.strip())

    def get_b2_credentials(self) -> tuple[str | None, str | None]:
        return (
            keyring.get_password(SERVICE, "b2_access_key_id"),
            keyring.get_password(SERVICE, "b2_application_key"),
        )

    def clear_b2_credentials(self):
        for key in ("b2_access_key_id", "b2_application_key"):
            try:
                keyring.delete_password(SERVICE, key)
            except Exception:
                pass

    def get_b2_runtime_config(self) -> dict:
        meta = dict(self.data.get("b2") or {})
        access_key_id, application_key = self.get_b2_credentials()
        meta["access_key_id"] = access_key_id or ""
        meta["application_key"] = application_key or ""
        meta["configured"] = bool(
            meta.get("enabled")
            and meta.get("bucket")
            and meta.get("endpoint_url")
            and access_key_id
            and application_key
        )
        return meta


    # KC Communication machine token stays only in the OS credential store.
    def ensure_kc_device_token(self) -> str:
        import secrets
        token = keyring.get_password(SERVICE, "kc_machine_device_token")
        if not token:
            token = secrets.token_urlsafe(48)
            keyring.set_password(SERVICE, "kc_machine_device_token", token)
        return token

    def get_kc_device_token(self) -> str | None:
        return keyring.get_password(SERVICE, "kc_machine_device_token")

    def clear_kc_device_token(self):
        try: keyring.delete_password(SERVICE, "kc_machine_device_token")
        except Exception: pass

    # Compatibility aliases for older 1.6.x code.
    def set_kc_token(self, token: str):
        if (token or "").strip(): keyring.set_password(SERVICE, "kc_machine_device_token", token.strip())
    def get_kc_token(self): return self.get_kc_device_token()
    def clear_kc_token(self): self.clear_kc_device_token()

    def add_plan(self, plan: dict) -> str:
        pid = plan.get("id") or str(uuid.uuid4())
        item = {
            "id": pid,
            "name": plan.get("name") or "Mein Backup",
            "paths": list(plan.get("paths") or []),
            "profile_id": plan.get("profile_id") or self.data.get("active_profile_id"),
            "enabled": bool(plan.get("enabled", True)),
            "schedule_type": plan.get("schedule_type", "MANUAL"),
            "schedule_time": plan.get("schedule_time", "20:00"),
            "weekday": plan.get("weekday", "MON"),
            "last_run": plan.get("last_run"),
            "last_status": plan.get("last_status"),
            "payload_target": plan.get("payload_target", "AUTO"),
            "secondary_copy_enabled": bool(plan.get("secondary_copy_enabled", False)),
            "secondary_profile_id": plan.get("secondary_profile_id"),
            "last_secondary_status": plan.get("last_secondary_status"),
        }
        self.data["plans"].append(item)
        if not self.data.get("default_plan_id"):
            self.data["default_plan_id"] = pid
        self.save()
        return pid

    def get_plan(self, pid: str | None = None) -> dict | None:
        pid = pid or self.data.get("default_plan_id")
        return next((p for p in self.data.get("plans", []) if p.get("id") == pid), None)

    def update_plan(self, pid: str, values: dict):
        p = self.get_plan(pid)
        if not p:
            raise KeyError(pid)
        p.update(values)
        self.save()

    def delete_plan(self, pid: str):
        self.data["plans"] = [p for p in self.data.get("plans", []) if p.get("id") != pid]
        if self.data.get("default_plan_id") == pid:
            self.data["default_plan_id"] = self.data["plans"][0]["id"] if self.data["plans"] else None
        self.save()

    def set_default_plan(self, pid: str):
        if self.get_plan(pid):
            self.data["default_plan_id"] = pid
            self.save()
