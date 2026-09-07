from __future__ import annotations

from tkinter import messagebox


def apply_professional_v180(AppClass, AssistantClass=None):
    """Consolidate 1.8.0 professional filesystem behavior behind existing UI paths."""
    import storage_v180
    from professional_v180 import (
        preflight_filesystem_target,
        run_filesystem_lifecycle,
        open_restore_route,
    )

    if not getattr(storage_v180, "_professional_wrapped", False):
        original_backup = storage_v180.filesystem_backup

        def professional_filesystem_backup(app, paths, target, control=None, progress=None, plan_name=None):
            paths = list(paths or [])
            expected = 0
            for p in paths:
                try: expected += int(p.stat().st_size)
                except Exception: pass
            pre = preflight_filesystem_target(target, paths, expected)
            if not pre.get("ok"):
                failures = [x.get("detail") for x in pre.get("checks", []) if not x.get("ok")]
                raise RuntimeError("Backup-Ziel-Prüfung fehlgeschlagen:\n" + "\n".join(f"• {x}" for x in failures))
            result = original_backup(app, paths, target, control=control, progress=progress, plan_name=plan_name)
            store = getattr(app, "store", None)
            key = app.master_key() if hasattr(app, "master_key") else None
            if store is not None and key:
                plan = next((p for p in store.data.get("plans", []) if str(p.get("name")) == str(plan_name)), None) if plan_name else None
                if plan:
                    try:
                        run_filesystem_lifecycle(store, plan, target, result, key)
                        if result.get("verification", {}).get("status") == "FAIL":
                            result["status"] = "SUCCESS_VERIFY_FAIL"
                        if result.get("selftest", {}).get("status") == "FAIL":
                            result["status"] = "SUCCESS_RESTORETEST_FAIL"
                    except Exception as e:
                        result["lifecycle_warning"] = str(e)
            return result

        storage_v180.filesystem_backup = professional_filesystem_backup
        storage_v180._professional_wrapped = True

    # Existing restore button/explorer stays untouched; the assistant offers the simple routing choice.
    if AssistantClass is not None:
        def finish_restore(self):
            self.destroy()
            try:
                open_restore_route(self.app)
            except Exception as e:
                messagebox.showerror("Rücksicherung", str(e), parent=self.app)
        AssistantClass.finish_restore = finish_restore

    # Also expose one quiet entry point on App for future TÜV/status integration without another main button.
    AppClass.open_offline_restore_v180 = lambda self: open_restore_route(self)
