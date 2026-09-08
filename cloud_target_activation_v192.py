from __future__ import annotations

from storage_v180 import DISPLAY, _update_target_text


def _filesystem_targets(store):
    return list(store.data.get("filesystem_targets") or [])


def target_state(store, account_id: str | None) -> dict:
    if not account_id:
        return {"prepared": False, "active": False, "target": None}
    target = next((
        t for t in _filesystem_targets(store)
        if str(t.get("cloud_account_id") or "") == str(account_id)
    ), None)
    active = bool(target and store.data.get("active_filesystem_target_id") == target.get("id"))
    return {"prepared": bool(target), "active": active, "target": target}


def _activate_account_target(tab) -> dict:
    state = target_state(tab.store, getattr(tab, "current_id", None))
    target = state.get("target")
    if not target:
        return state

    tab.store.data["active_filesystem_target_id"] = target.get("id")
    tab.store.data["payload_target_default"] = "FILESYSTEM"
    tab.store.save()

    app = getattr(getattr(tab, "settings", None), "app", None)
    if app is not None:
        try:
            app.payload_var.set(DISPLAY)
        except Exception:
            pass
        try:
            _update_target_text(app)
        except Exception:
            pass
        try:
            app.update_backup_recommendation()
        except Exception:
            pass
    return target_state(tab.store, getattr(tab, "current_id", None))


def apply_cloud_target_activation_v192(cloud_ui_module):
    cls = cloud_ui_module.CloudTargetsTab
    if getattr(cls, "_target_activation_v192", False):
        return cls

    original_build = cls._build
    original_refresh = cls.refresh_list
    original_load = cls.load_account
    original_new = cls.new_account
    original_publish = cls.publish_backup_target

    def _refresh_target_status(self):
        state = target_state(self.store, getattr(self, "current_id", None))
        label = getattr(self, "backup_target_status_v192", None)
        if label is None:
            return state
        if state["active"]:
            text = "Backup-Ziel: ✓ bereitgestellt und AKTIV – der nächste manuelle Dateispeicher-Backupjob verwendet dieses Ziel."
        elif state["prepared"]:
            text = "Backup-Ziel: ✓ bereitgestellt, aber derzeit NICHT aktiv."
        else:
            text = "Backup-Ziel: noch nicht bereitgestellt."
        label.configure(text=text)
        return state

    def _build(self):
        original_build(self)
        self.backup_target_status_v192 = cloud_ui_module.ttk.Label(
            self,
            text="Backup-Ziel: noch nicht bereitgestellt.",
            font=("Segoe UI", 9, "bold"),
            wraplength=930,
            justify="left",
        )
        self.backup_target_status_v192.pack(anchor="w", pady=(8, 0))
        _refresh_target_status(self)

    def refresh_list(self, select_id=None):
        result = original_refresh(self, select_id)
        _refresh_target_status(self)
        return result

    def load_account(self, account_id):
        result = original_load(self, account_id)
        _refresh_target_status(self)
        return result

    def new_account(self):
        result = original_new(self)
        _refresh_target_status(self)
        return result

    def publish_backup_target(self):
        original_publish(self)
        state = _activate_account_target(self)
        _refresh_target_status(self)
        if state.get("active"):
            try:
                self.status.configure(text=f"✓ Als Backup-Ziel bereitgestellt und AKTIV: {state['target'].get('name')}")
            except Exception:
                pass

    cls._build = _build
    cls.refresh_list = refresh_list
    cls.load_account = load_account
    cls.new_account = new_account
    cls.publish_backup_target = publish_backup_target
    cls._refresh_target_status_v192 = _refresh_target_status
    cls._target_activation_v192 = True
    return cls
