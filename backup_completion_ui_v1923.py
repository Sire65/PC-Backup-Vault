from __future__ import annotations


def target_description(app) -> str:
    """Describe the destination that the current backup run will use."""
    try:
        code = str(app._selected_payload_code() or "").upper()
    except Exception:
        code = ""

    if code == "B2":
        return "Backblaze B2 + Neon-Core"
    if code == "NEON":
        return "Neon – nur Kleinmengen"

    if code == "FILESYSTEM":
        try:
            store = app.store
            tid = store.data.get("active_filesystem_target_id")
            target = next((x for x in store.data.get("filesystem_targets", []) if x.get("id") == tid), None)
            if target:
                name = str(target.get("name") or "Dateispeicher")
                path = str(target.get("path") or "–")
                account_id = str(target.get("cloud_account_id") or "")
                if account_id:
                    account = next((x for x in store.data.get("cloud_accounts", []) if str(x.get("id")) == account_id), None)
                    account_name = str((account or {}).get("name") or name).replace("Cloud · ", "")
                    provider = str((account or {}).get("provider") or "").upper()
                    if provider == "STRATO_HIDRIVE" or str(target.get("cloud_method") or "").upper() == "SFTP":
                        return f"STRATO HiDrive · {account_name} · {path}"
                return f"{name} · {path}"
        except Exception:
            pass

    try:
        text = str(app.lbl_target.cget("text") or "").strip()
        if text.lower().startswith("ziel:"):
            text = text.split(":", 1)[1].strip()
        if text and text != "–":
            return text
    except Exception:
        pass
    return "–"


def is_hidrive_success(event, title, details) -> bool:
    if str(event or "").lower() != "backup_success":
        return False
    if not str((details or {}).get("job_id") or "").strip():
        return False
    marker = f"{title or ''} {(details or {}).get('target') or ''}".lower()
    return "hidrive" in marker or "strato" in marker


def apply_backup_completion_ui_v1923(AppClass, ui_module):
    """Add exact target visibility and open the normal report after HiDrive success.

    This wraps only UI completion/progress hooks. Backup, crypto and transport
    implementations remain untouched.
    """
    if getattr(AppClass, "_backup_completion_ui_v1923", False):
        return
    AppClass._backup_completion_ui_v1923 = True

    original_begin = AppClass._begin_backup_control
    original_progress = AppClass._progress
    original_notify = AppClass.notify_kc

    def _ensure_target_label(self, explicit=None):
        mon = getattr(self, "_transfer_monitor_v180", None)
        try:
            if not mon or not mon.winfo_exists():
                return
            label = getattr(mon, "target_v1923", None)
            if label is None or not label.winfo_exists():
                from tkinter import ttk
                label = ttk.Label(mon.current.master, text="Ziel: –", wraplength=570)
                label.pack(anchor="w", pady=(4, 0), after=mon.current)
                mon.target_v1923 = label
            label.config(text=f"Ziel: {explicit or target_description(self)}")
        except Exception:
            pass

    def _begin_backup_control(self):
        control = original_begin(self)
        try:
            self.after(0, lambda: _ensure_target_label(self))
        except Exception:
            _ensure_target_label(self)
        return control

    def _progress(self, d, t, message, metrics=None):
        result = original_progress(self, d, t, message, metrics)
        m = dict(metrics or {})
        exact = str(m.get("target_label") or m.get("target") or "").strip()
        _ensure_target_label(self, exact or None)
        return result

    def notify_kc(self, event, title, message, severity="INFO", details=None):
        result = original_notify(self, event, title, message, severity, details)
        if is_hidrive_success(event, title, details):
            jid = str((details or {}).get("job_id") or "").strip()
            if jid and getattr(self, "_auto_report_job_v1923", None) != jid:
                self._auto_report_job_v1923 = jid
                def open_report():
                    try:
                        ui_module.JobReportWindow(self, jid)
                    except Exception:
                        # A failed report window must never turn a successful
                        # backup into a failed backup.
                        pass
                try:
                    self.after(250, open_report)
                except Exception:
                    pass
        return result

    AppClass._begin_backup_control = _begin_backup_control
    AppClass._progress = _progress
    AppClass.notify_kc = notify_kc
