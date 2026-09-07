from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox

from storage_v180 import DISPLAY, CODE, _targets, _target, add_or_select_target


def apply_settings_v180(SettingsWindow):
    original_build_plans=SettingsWindow._build_plans
    original_load=SettingsWindow.load_selected_plan
    original_save=SettingsWindow.save_plan
    original_run_now=SettingsWindow.run_plan_now

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

    def _manage_target(self):
        add_or_select_target(self.app)
        self.after(150,self._refresh_fs_targets)

    def _build_plans(self):
        original_build_plans(self)
        self.plan_fs_target=tk.StringVar()
        parent=self.plan_payload_combo.master
        ttk.Label(parent,text="Laufwerk / Ordner / NAS").grid(row=2,column=0,sticky="w",pady=(7,4),padx=(0,8))
        row=ttk.Frame(parent); row.grid(row=2,column=1,sticky="ew",pady=(7,4)); row.columnconfigure(0,weight=1)
        self.plan_fs_target_combo=ttk.Combobox(row,textvariable=self.plan_fs_target,state="readonly",values=_target_names(self))
        self.plan_fs_target_combo.grid(row=0,column=0,sticky="ew")
        ttk.Button(row,text="📁 Ziele …",command=lambda:_manage_target(self)).grid(row=0,column=1,padx=(6,0))
        ttk.Label(parent,text="Bei 'USB / externe Platte / Ordner / NAS' wird dieses konkrete Ziel für den Plan gespeichert.",wraplength=650).grid(row=3,column=0,columnspan=2,sticky="w",pady=(2,0))
        self.plan_payload_combo.bind("<<ComboboxSelected>>",lambda e:self._update_fs_target_state(),add="+")
        self._refresh_fs_targets()
        self._update_fs_target_state()

    def _update_fs_target_state(self):
        state="readonly" if self.plan_payload.get()==DISPLAY else "disabled"
        try:self.plan_fs_target_combo.configure(state=state)
        except Exception:pass

    def load_selected_plan(self):
        original_load(self)
        p=self.selected_plan()
        if p:
            t=_target(self.store,p.get("filesystem_target_id"))
            if t:self.plan_fs_target.set(t.get("name") or "")
            elif self.plan_payload.get()==DISPLAY:
                active=_target(self.store); self.plan_fs_target.set((active or {}).get("name") or "")
        self._refresh_fs_targets(); self._update_fs_target_state()

    def save_plan(self):
        if self.plan_payload.get()==DISPLAY and not self.plan_fs_target.get():
            messagebox.showerror("PC Backup Vault","Für dieses Dateisystem-Backup muss ein Laufwerk, Ordner oder NAS-Ziel ausgewählt werden.",parent=self); return None
        pid=original_save(self)
        if not pid:return pid
        tid=_target_id_by_name(self,self.plan_fs_target.get()) if self.plan_payload.get()==DISPLAY else None
        self.store.update_plan(pid,{"filesystem_target_id":tid})
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
    SettingsWindow.load_selected_plan=load_selected_plan
    SettingsWindow.save_plan=save_plan
    SettingsWindow.run_plan_now=run_plan_now
