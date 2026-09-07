from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox


def apply_professional_v180(AppClass, AssistantClass=None, SettingsWindow=None, ui_module=None):
    """Consolidate 1.8.0 professional filesystem behavior behind existing UI paths."""
    import storage_v180
    from professional_v180 import (
        preflight_filesystem_target,
        run_filesystem_lifecycle,
        open_restore_route,
        filesystem_tuev_checks,
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
                        if result.get("verification", {}).get("status") == "FAIL": result["status"] = "SUCCESS_VERIFY_FAIL"
                        if result.get("selftest", {}).get("status") == "FAIL": result["status"] = "SUCCESS_RESTORETEST_FAIL"
                    except Exception as e:
                        result["lifecycle_warning"] = str(e)
            return result

        storage_v180.filesystem_backup = professional_filesystem_backup
        storage_v180._professional_wrapped = True

    if AssistantClass is not None:
        # Extend the existing options step without introducing another wizard page.
        original_options = AssistantClass.step_options
        def step_options(self):
            original_options(self)
            self.data.setdefault("restore_test", True)
            self.data.setdefault("keep_last_versions", 10)
            self.data.setdefault("retention_days", 90)
            sep=ttk.Separator(self.body,orient="horizontal"); sep.pack(fill="x",pady=(14,10))
            ttk.Label(self.body,text="Sicherheit & Aufbewahrung",font=("Segoe UI",10,"bold")).pack(anchor="w")
            restore=tk.BooleanVar(value=bool(self.data.get("restore_test",True)))
            ttk.Checkbutton(self.body,text="Nach dem Backup eine kleine echte Restore-Probe durchführen",variable=restore,command=lambda:self.data.update(restore_test=restore.get())).pack(anchor="w",pady=(6,5))
            row=ttk.Frame(self.body); row.pack(fill="x",pady=3)
            ttk.Label(row,text="Mindestens").pack(side="left")
            keep=tk.StringVar(value=str(self.data.get("keep_last_versions",10)))
            ttk.Combobox(row,textvariable=keep,state="readonly",values=("3","5","10","20","30"),width=5).pack(side="left",padx=5)
            ttk.Label(row,text="Backup-Stände behalten und mindestens").pack(side="left")
            days=tk.StringVar(value=str(self.data.get("retention_days",90)))
            ttk.Combobox(row,textvariable=days,state="readonly",values=("30","60","90","180","365"),width=6).pack(side="left",padx=5)
            ttk.Label(row,text="Tage aufbewahren.").pack(side="left")
            def sync(*_):
                self.data["restore_test"]=restore.get(); self.data["keep_last_versions"]=int(keep.get()); self.data["retention_days"]=int(days.get())
            keep.trace_add("write",sync); days.trace_add("write",sync); sync()

        original_finish = AssistantClass.finish
        def finish(self):
            # Existing finish stores the core plan. Capture the selected professional defaults so
            # they can be persisted by temporarily wrapping update_plan for the newly-created plan.
            store=self.store; before={p.get("id") for p in store.data.get("plans",[])}
            original_finish(self)
            after=[p for p in store.data.get("plans",[]) if p.get("id") not in before]
            if after:
                p=after[-1]
                store.update_plan(p["id"],{
                    "restore_test":bool(self.data.get("restore_test",True)),
                    "keep_last_versions":int(self.data.get("keep_last_versions",10)),
                    "retention_days":int(self.data.get("retention_days",90)),
                })
        def finish_restore(self):
            self.destroy()
            try: open_restore_route(self.app)
            except Exception as e: messagebox.showerror("Rücksicherung", str(e), parent=self.app)
        AssistantClass.step_options = step_options
        AssistantClass.finish = finish
        AssistantClass.finish_restore = finish_restore

    if SettingsWindow is not None:
        original_build = SettingsWindow._build_plans
        original_load = SettingsWindow.load_selected_plan
        original_save = SettingsWindow.save_plan
        def _build_plans(self):
            original_build(self)
            self.plan_restore_test_v180=tk.BooleanVar(value=True)
            self.plan_keep_v180=tk.StringVar(value="10")
            self.plan_days_v180=tk.StringVar(value="90")
            frame=ttk.LabelFrame(self.plantab,text="Sicherheit / Aufbewahrung",padding=8)
            frame.pack(side="bottom",fill="x",pady=(6,0))
            ttk.Checkbutton(frame,text="Verifikation + kleine Restore-Probe nach Backup",variable=self.plan_restore_test_v180).pack(side="left")
            ttk.Label(frame,text="Stände:").pack(side="left",padx=(18,4))
            ttk.Combobox(frame,textvariable=self.plan_keep_v180,state="readonly",values=("3","5","10","20","30"),width=5).pack(side="left")
            ttk.Label(frame,text="mind. Tage:").pack(side="left",padx=(12,4))
            ttk.Combobox(frame,textvariable=self.plan_days_v180,state="readonly",values=("30","60","90","180","365"),width=6).pack(side="left")
            ttk.Label(frame,text="  (alte, nicht mehr benötigte Daten werden referenzsicher bereinigt)").pack(side="left")
        def load_selected_plan(self):
            original_load(self); p=self.selected_plan()
            if p:
                self.plan_restore_test_v180.set(bool(p.get("restore_test",True)))
                self.plan_keep_v180.set(str(p.get("keep_last_versions",self.store.data.get("keep_last_versions",10))))
                self.plan_days_v180.set(str(p.get("retention_days",self.store.data.get("retention_days",90))))
        def save_plan(self):
            pid=original_save(self)
            if pid:
                self.store.update_plan(pid,{
                    "restore_test":bool(self.plan_restore_test_v180.get()),
                    "auto_verify":bool(self.plan_restore_test_v180.get()),
                    "keep_last_versions":int(self.plan_keep_v180.get()),
                    "retention_days":int(self.plan_days_v180.get()),
                })
            return pid
        SettingsWindow._build_plans=_build_plans
        SettingsWindow.load_selected_plan=load_selected_plan
        SettingsWindow.save_plan=save_plan

    # Extend existing TÜV results instead of creating another TÜV screen/button.
    if ui_module is not None and hasattr(ui_module,"run_tuev"):
        original_tuev=ui_module.run_tuev
        def run_tuev_professional(dsn,key_present,recovery_exported,profile,config):
            checks=original_tuev(dsn,key_present,recovery_exported,profile,config)
            try:
                from config_store import ConfigStore
                store=ConfigStore(); key=store.get_master_key()
                extra=filesystem_tuev_checks(store,key) if key else [("FS-SEC","Offline-Tresor-Prüfung","FAIL","Master-Key fehlt")]
                checks.extend(extra)
                try:
                    import psycopg
                    with psycopg.connect(dsn) as conn:
                        for c in extra:
                            conn.execute("INSERT INTO backup_vault.tuev_checks(check_code,check_name,result,details,app_version,schema_version) VALUES (%s,%s,%s,%s,%s,%s)",(c[0],c[1],c[2],c[3],config.get("app_version","1.8.0"),"1.8.0"))
                        conn.commit()
                except Exception: pass
            except Exception as e:
                checks.append(("FS-999","Offline-Tresor-TÜV","FAIL",str(e)))
            return checks
        ui_module.run_tuev=run_tuev_professional

    AppClass.open_offline_restore_v180 = lambda self: open_restore_route(self)
