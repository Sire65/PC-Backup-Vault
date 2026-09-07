from __future__ import annotations

import threading
from datetime import datetime
from tkinter import messagebox

from backup_engine import BackupCancelled, collect_paths
from hidrive_sftp_v192 import filesystem_backup_sftp, test_hidrive_sftp


def _is_sftp_target(target):
    return bool(target and str(target.get("cloud_method") or "").upper() == "SFTP" and target.get("cloud_account_id"))


def apply_hidrive_sftp_v192(AppClass, cloud_core, cloud_ui, storage_module, plan_runner_module):
    if getattr(AppClass, "_hidrive_sftp_v192", False):
        return

    original_test = cloud_core.test_cloud_account
    original_capable = cloud_core.filesystem_capable_method
    original_bridge = cloud_core.ensure_filesystem_bridge
    original_prepare = cloud_core.prepare_cloud_filesystem_target

    def filesystem_capable_method(account):
        methods = [str(x).upper() for x in (account.get("methods") or [])]
        preferred = str(account.get("preferred_method") or "").upper()
        order = [preferred] + [x for x in methods if x != preferred]
        for method in order:
            if method == "SFTP":
                return "SFTP"
        return original_capable(account)

    def test_cloud_account(store, account_id, method=None):
        account = cloud_core.cloud_account(store, account_id)
        selected = str(method or (account or {}).get("preferred_method") or "").upper()
        if selected == "SFTP":
            return test_hidrive_sftp(store, account_id)
        return original_test(store, account_id, method)

    def ensure_filesystem_bridge(store, account_id):
        account = cloud_core.cloud_account(store, account_id)
        if account and filesystem_capable_method(account) == "SFTP":
            username = str(account.get("username") or "").strip()
            if not username:
                raise ValueError("Für STRATO HiDrive fehlt der Benutzername.")
            root = str(account.get("root_path") or "").strip()
            if not root:
                root = f"/users/{username}/PC_Backup_Vault"
                account["root_path"] = root
                store.save()
            elif not root.startswith("/"):
                root = f"/users/{username}/{root.strip('/')}"
                account["root_path"] = root
                store.save()
            target_id = f"cloud-{account_id}"
            item = {
                "id": target_id,
                "name": f"Cloud · {account.get('name') or 'STRATO HiDrive'}",
                "path": root,
                "kind": "CLOUD-SFTP",
                "volume_hint": "CLOUD",
                "cloud_account_id": account_id,
                "cloud_method": "SFTP",
            }
            rows = store.data.setdefault("filesystem_targets", [])
            old = next((x for x in rows if x.get("id") == target_id), None)
            if old is None:
                rows.append(item)
            else:
                old.clear(); old.update(item)
            store.data["active_filesystem_target_id"] = target_id
            store.save()
            return item
        return original_bridge(store, account_id)

    def prepare_cloud_filesystem_target(store, target):
        if _is_sftp_target(target):
            account = cloud_core.cloud_account(store, target.get("cloud_account_id"))
            if not account or not account.get("enabled", True):
                raise RuntimeError("Das HiDrive-Konto ist deaktiviert oder wurde gelöscht.")
            target = dict(target)
            target["path"] = str(account.get("root_path") or target.get("path") or "")
            return target
        return original_prepare(store, target)

    cloud_core.filesystem_capable_method = filesystem_capable_method
    cloud_core.test_cloud_account = test_cloud_account
    cloud_core.ensure_filesystem_bridge = ensure_filesystem_bridge
    cloud_core.prepare_cloud_filesystem_target = prepare_cloud_filesystem_target

    cloud_ui.filesystem_capable_method = filesystem_capable_method
    cloud_ui.test_cloud_account = test_cloud_account
    cloud_ui.ensure_filesystem_bridge = ensure_filesystem_bridge

    original_fs_backup = storage_module.filesystem_backup

    def filesystem_backup(app, paths, target, control=None, progress=None, plan_name=None):
        if _is_sftp_target(target):
            return filesystem_backup_sftp(app, paths, target, control, progress, plan_name)
        return original_fs_backup(app, paths, target, control, progress, plan_name)

    storage_module.filesystem_backup = filesystem_backup

    original_headless = plan_runner_module._run_filesystem_plan

    def _run_filesystem_plan(store, plan, paths, key, progress=None, control=None):
        target_id = plan.get("filesystem_target_id")
        target = storage_module._target(store, target_id) if target_id else None
        if _is_sftp_target(target):
            target = prepare_cloud_filesystem_target(store, dict(target))

            class _HeadlessApp:
                def __init__(self, store_, key_):
                    self.store = store_
                    self._key = key_
                def master_key(self):
                    return self._key

            return filesystem_backup_sftp(
                _HeadlessApp(store, key), paths, target, control=control,
                progress=progress, plan_name=plan.get("name"),
            )
        return original_headless(store, plan, paths, key, progress=progress, control=control)

    plan_runner_module._run_filesystem_plan = _run_filesystem_plan

    original_run_plan_ui = AppClass._run_plan_v180
    original_start_backup = AppClass.start_backup

    def _run_sftp_job(self, paths, target, plan=None):
        total = sum(p.stat().st_size for p in paths)
        self._reset_live_progress(len(paths), total)
        control = self._begin_backup_control()

        def cb(done, total_files, msg, metrics=None):
            self.after(0, lambda: self._progress(done, total_files, msg, metrics))

        def work():
            try:
                result = filesystem_backup_sftp(
                    self, paths, target, control=control, progress=cb,
                    plan_name=(plan or {}).get("name"),
                )
                if plan:
                    plan["last_run"] = datetime.now().isoformat(timespec="seconds")
                    plan["last_status"] = "SUCCESS"
                    self.store.save()
                text = f"HiDrive-Backup abgeschlossen – {result['files']} Dateien."
                self.after(0, lambda: self.lbl_progress.config(text=text))
                self.notify_kc(
                    "backup_success", "STRATO HiDrive Backup erfolgreich", text, "INFO",
                    {"job_id": result["job_id"], "target": target.get("name"), "files": result["files"]},
                )
            except BackupCancelled:
                if plan:
                    plan["last_run"] = datetime.now().isoformat(timespec="seconds")
                    plan["last_status"] = "CANCELLED"
                    self.store.save()
                self.after(0, lambda: messagebox.showinfo("PC Backup Vault", "HiDrive-Backup wurde abgebrochen.", parent=self))
            except Exception as exc:
                msg = str(exc)
                if plan:
                    plan["last_run"] = datetime.now().isoformat(timespec="seconds")
                    plan["last_status"] = "FAILED"
                    self.store.save()
                self.notify_kc("backup_failed", "STRATO HiDrive Backup fehlgeschlagen", msg, "ERROR")
                self.after(0, lambda m=msg: messagebox.showerror("PC Backup Vault", m, parent=self))
            finally:
                self.after(0, lambda: self._set_backup_running(False))

        threading.Thread(target=work, name="pbv-hidrive-sftp", daemon=True).start()

    def _run_plan_v180(self, plan):
        if str(plan.get("payload_target") or "").upper() == storage_module.CODE:
            target = storage_module._target(self.store, plan.get("filesystem_target_id"))
            if _is_sftp_target(target):
                paths = collect_paths(plan.get("paths") or [])
                if not paths:
                    messagebox.showwarning("One-Touch", "Der gewählte Plan enthält keine erreichbaren Dateien/Ordner.", parent=self)
                    return
                return _run_sftp_job(self, paths, target, plan)
        return original_run_plan_ui(self, plan)

    def start_backup(self, resume_checkpoint=None):
        if resume_checkpoint is None and getattr(self, "payload_var", None) is not None:
            if self.payload_var.get() == storage_module.DISPLAY:
                target = storage_module._target(self.store)
                if _is_sftp_target(target):
                    if not self.selected:
                        messagebox.showwarning("PC Backup Vault", "Bitte zuerst Dateien oder einen Ordner auswählen.", parent=self)
                        return
                    return _run_sftp_job(self, list(self.selected), target, None)
        return original_start_backup(self, resume_checkpoint)

    AppClass._run_plan_v180 = _run_plan_v180
    AppClass.start_backup = start_backup
    AppClass._hidrive_sftp_v192 = True
