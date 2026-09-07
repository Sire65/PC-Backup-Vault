from __future__ import annotations

import os
import tkinter as tk
from tkinter import ttk, messagebox

from storage_v180 import DISPLAY, CODE, _targets, _target, add_or_select_target
from scheduler import install_task, remove_task


def apply_settings_v180(SettingsWindow):
    original_build_plans=SettingsWindow._build_plans
    original_load=SettingsWindow.load_selected_plan
    original_save=SettingsWindow.save_plan
    original_run_now=SettingsWindow.run_plan_now
    original_new_plan=SettingsWindow.new_plan

    def _target_names(self):
        return [str(t.get("name") or "Backup-Ziel") for t in _targets(self.store)]

    def _target_id_by_name(self,name):
        return next((t.get("id") for t in _targets(self.store) if t.get("name")==name),None)

    def _refresh_fs_targets(self):
        values=_target_names(self)
        try:self.plan_fs_target_combo.configure(values=values)
        except Exception:return
        if self.plan_fs_target.get() not in values:
            active=_target(self.store)
            self.plan_fs_target.set((active or {}).get("name") or (values[0] if values else ""))
        self._update_job_summary_v180()

    def _manage_target(self):
        add_or_select_target(self.app)
        self.after(150,self._refresh_fs_targets)

    def _build_plans(self):
        original_build_plans(self)

        # 1.8.0: one job definition drives both One-Touch and Windows Scheduler.
        self.plan_fs_target=tk.StringVar()
        self.plan_scheduler_auto=tk.BooleanVar(value=True)

        parent=self.plan_payload_combo.master
        ttk.Separator(parent,orient="horizontal").grid(row=2,column=0,columnspan=2,sticky="ew",pady=(8,6))
        ttk.Label(parent,text="Konkretes Laufwerk / Ordner / NAS").grid(row=3,column=0,sticky="w",pady=4,padx=(0,8))
        row=ttk.Frame(parent); row.grid(row=3,column=1,sticky="ew",pady=4); row.columnconfigure(0,weight=1)
        self.plan_fs_target_combo=ttk.Combobox(row,textvariable=self.plan_fs_target,state="readonly",values=_target_names(self))
        self.plan_fs_target_combo.grid(row=0,column=0,sticky="ew")
        ttk.Button(row,text="📁 Ziel auswählen / anlegen …",command=lambda:_manage_target(self)).grid(row=0,column=1,padx=(6,0))
        ttk.Label(parent,text="Für USB, externe SSD/HDD, lokale Ordner und NAS wird dieses konkrete Ziel fest im Job gespeichert.",wraplength=650).grid(row=4,column=0,columnspan=2,sticky="w",pady=(2,2))

        # Scheduler comfort block. Manual means One-Touch only; any schedule can be installed automatically on save.
        sched=ttk.LabelFrame(self.plantab,text="Komfort / Ausführung",padding=8)
        # Insert at bottom of the plan tab without disturbing the existing form geometry.
        sched.pack(side="bottom",fill="x",pady=(8,0))
        ttk.Checkbutton(
            sched,
            text="Zeitplan beim Speichern automatisch an den Windows-Scheduler übergeben",
            variable=self.plan_scheduler_auto,
            command=self._update_job_summary_v180,
        ).pack(anchor="w")
        ttk.Label(
            sched,
            text="Manuell = reiner One-Touch-Job. Bei Täglich/Wöchentlich/Windows-Anmeldung kann derselbe Job zusätzlich automatisch laufen.",
            wraplength=880,
        ).pack(anchor="w",pady=(3,6))
        self.lbl_job_summary_v180=ttk.Label(sched,text="Job-Zusammenfassung: –",wraplength=900,justify="left")
        self.lbl_job_summary_v180.pack(anchor="w")

        self.plan_payload_combo.bind("<<ComboboxSelected>>",lambda e:(self._update_fs_target_state(),self._update_job_summary_v180()),add="+")
        self.plan_fs_target_combo.bind("<<ComboboxSelected>>",lambda e:self._update_job_summary_v180(),add="+")
        self.plan_type_combo.bind("<<ComboboxSelected>>",lambda e:self._update_job_summary_v180(),add="+")
        for var in (self.plan_name,self.plan_time,self.plan_day):
            try:var.trace_add("write",lambda *_:self._update_job_summary_v180())
            except Exception:pass
        self._refresh_fs_targets()
        self._update_fs_target_state()
        self._update_job_summary_v180()

    def _update_fs_target_state(self):
        state="readonly" if self.plan_payload.get()==DISPLAY else "disabled"
        try:self.plan_fs_target_combo.configure(state=state)
        except Exception:pass
        self._update_job_summary_v180()

    def _update_job_summary_v180(self):
        if not hasattr(self,"lbl_job_summary_v180"):return
        name=(self.plan_name.get().strip() if hasattr(self,"plan_name") else "") or "Neuer Backup-Job"
        source_count=0
        try:source_count=int(self.pathlist.size())
        except Exception:pass
        payload=self.plan_payload.get() if hasattr(self,"plan_payload") else "–"
        if payload==DISPLAY:
            destination=self.plan_fs_target.get().strip() or "noch kein Ziel gewählt"
        elif payload=="Backblaze B2":
            destination="Backblaze B2 + Neon-Core"
        elif payload.startswith("Neon"):
            destination="Neon"
        else:
            destination=payload or "Automatisch"
        schedule=self.plan_type.get() if hasattr(self,"plan_type") else "Manuell"
        detail=schedule
        if schedule=="Täglich":detail=f"täglich um {self.plan_time.get() or '–'}"
        elif schedule=="Wöchentlich":detail=f"{self.plan_day.get() or '–'} um {self.plan_time.get() or '–'}"
        elif schedule=="Bei Windows-Anmeldung":detail="bei Windows-Anmeldung"
        auto=" · Scheduler wird beim Speichern aktualisiert" if schedule!="Manuell" and self.plan_scheduler_auto.get() else ""
        self.lbl_job_summary_v180.config(text=f"Job-Zusammenfassung: {name} · {source_count} Quelle(n) · Ziel: {destination} · Ausführung: {detail}{auto}")

    def load_selected_plan(self):
        original_load(self)
        p=self.selected_plan()
        if p:
            t=_target(self.store,p.get("filesystem_target_id"))
            if t:self.plan_fs_target.set(t.get("name") or "")
            elif self.plan_payload.get()==DISPLAY:
                active=_target(self.store); self.plan_fs_target.set((active or {}).get("name") or "")
            self.plan_scheduler_auto.set(bool(p.get("scheduler_auto_sync",True)))
        self._refresh_fs_targets(); self._update_fs_target_state(); self._update_job_summary_v180()

    def new_plan(self):
        original_new_plan(self)
        p=self.selected_plan()
        if p:
            self.store.update_plan(p["id"],{"scheduler_auto_sync":True,"filesystem_target_id":None})
            self.plan_scheduler_auto.set(True)
        self._update_job_summary_v180()

    def _validate_fs_target(self):
        if self.plan_payload.get()!=DISPLAY:
            return True
        name=self.plan_fs_target.get().strip()
        if not name:
            messagebox.showerror("PC Backup Vault","Für dieses Backup muss ein Laufwerk, Ordner oder NAS-Ziel ausgewählt werden.",parent=self); return False
        tid=_target_id_by_name(self,name); target=_target(self.store,tid)
        if not target:
            messagebox.showerror("PC Backup Vault","Das gewählte Dateisystem-Ziel wurde nicht gefunden.",parent=self); return False
        path=str(target.get("path") or "")
        if not path:
            messagebox.showerror("PC Backup Vault","Beim gewählten Ziel fehlt der Zielpfad.",parent=self); return False
        # Missing removable media may legitimately be offline while configuring; warn but allow save.
        if not os.path.exists(path):
            if not messagebox.askyesno(
                "Backup-Ziel derzeit nicht erreichbar",
                f"Das Ziel ist momentan nicht erreichbar:\n\n{path}\n\nDer Job kann trotzdem gespeichert werden. Beim Start wird erneut geprüft. Job jetzt trotzdem speichern?",
                parent=self,
            ):return False
        return True

    def save_plan(self):
        if not self._validate_fs_target():return None
        pid=original_save(self)
        if not pid:return pid
        tid=_target_id_by_name(self,self.plan_fs_target.get()) if self.plan_payload.get()==DISPLAY else None
        plan=self.store.get_plan(pid)
        self.store.update_plan(pid,{"filesystem_target_id":tid,"scheduler_auto_sync":bool(self.plan_scheduler_auto.get())})
        plan=self.store.get_plan(pid)

        # Keep Windows Scheduler synchronized with the same One-Touch job definition.
        sched_msg=""
        if plan and bool(self.plan_scheduler_auto.get()):
            if plan.get("schedule_type")=="MANUAL":
                # Remove stale automatic task if user changed a scheduled job back to manual.
                try:remove_task(plan)
                except Exception:pass
                sched_msg="\n\nOne-Touch: bereit. Kein automatischer Zeitplan gewählt."
            else:
                ok,msg=install_task(plan)
                sched_msg=("\n\nWindows-Scheduler: eingerichtet/aktualisiert." if ok else f"\n\nWindows-Scheduler konnte nicht aktualisiert werden:\n{msg}")
                if not ok:messagebox.showwarning("Scheduler",msg,parent=self)
        self._update_job_summary_v180()
        if sched_msg:
            messagebox.showinfo("PC Backup Vault",f"Job '{plan.get('name')}' vollständig gespeichert.{sched_msg}",parent=self)
        return pid

    def run_plan_now(self):
        pid=self.save_plan(); p=self.store.get_plan(pid) if pid else None
        if not p:return
        if (p.get("payload_target") or "AUTO").upper()==CODE:
            self.app._run_plan_v180(p)
            return
        return original_run_now(self)

    SettingsWindow._build_plans=_build_plans
    SettingsWindow._refresh_fs_targets=_refresh_fs_targets
    SettingsWindow._update_fs_target_state=_update_fs_target_state
    SettingsWindow._update_job_summary_v180=_update_job_summary_v180
    SettingsWindow.load_selected_plan=load_selected_plan
    SettingsWindow.new_plan=new_plan
    SettingsWindow.save_plan=save_plan
    SettingsWindow.run_plan_now=run_plan_now
