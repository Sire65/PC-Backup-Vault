import json, os, uuid
from pathlib import Path
import keyring

APP_NAME = "PCBackupVault"
SERVICE = "PC Backup Vault"
APP_VERSION = "1.9.3"


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
            "recovery_exported": False,
            "cloud_accounts": [],
            "filesystem_targets": [],
            "active_filesystem_target_id": None,
        }
        self.load()

    def load(self):
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict): self.data.update(loaded)
            except Exception: pass

    def save(self):
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    def get_master_key(self):
        return keyring.get_password(SERVICE, "master_key")

    def set_master_key(self, value):
        keyring.set_password(SERVICE, "master_key", value)

    def update_plan(self, plan_id, changes):
        for p in self.data.get("plans", []):
            if p.get("id") == plan_id:
                p.update(changes); self.save(); return plan_id
        return None
