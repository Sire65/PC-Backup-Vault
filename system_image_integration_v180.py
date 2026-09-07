from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox

from storage_v180 import _targets, _target, add_or_select_target
from system_image_v180 import create_system_image, recovery_instructions


class SystemImageWizard(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app=app; self.store=app.store
        self.title("PC Backup Vault – Windows-Systemabbild")
        self.geometry("760x520"); self.transient(app); self.grab_set()
        box=ttk.Frame(self,padding=16); box.pack(fill="both",expand=True)
        ttk.Label(box,text="Windows-Systemabbild / Bare-Metal",font=("Segoe UI",16,"bold")).pack(anchor="w")
        ttk.Label(box,text="Für defekte Systemplatten oder vollständige Wiederherstellung eines Rechners. Das Image bleibt bewusst Windows-/WinRE-kompatibel.",wraplength=710).pack(anchor="w",pady=(4,14))

        self.target_name=tk.StringVar()
        self.include_volume=tk.StringVar(value="C:")
        self.bitlocker_confirm=tk.BooleanVar(value=False)

        ttk.Label(box,text="Zielmedium").pack(anchor="w")
        self.target_combo=ttk.Combobox(box,textvariable=self.target_name,state="readonly",values=[t.get("name") for t in _targets(self.store)],width=52)
        self.target_combo.pack(anchor="w",pady=(3,5))
        ttk.Button(box,text="📁 Ziel auswählen / anlegen …",command=self.manage_target).pack(anchor="w")

        ttk.Label(box,text="Zusätzlich einzubeziehendes Volume (optional)").pack(anchor="w",pady=(14,3))
        ttk.Entry(box,textvariable=self.include_volume,width=14).pack(anchor="w")
        ttk.Label(box,text="Mit -allCritical nimmt Windows alle für den Systemstart nötigen Volumes auf. C: kann zusätzlich ausdrücklich angegeben werden.",wraplength=700).pack(anchor="w",pady=(4,12))

        sec=ttk.LabelFrame(box,text="Schutz des Systemabbilds",padding=10); sec.pack(fill="x",pady=(4,12))
        ttk.Label(sec,text="PC Backup Vault verschlüsselt dieses Image NICHT mit seinem eigenen AES-Container, weil Windows RE es sonst nicht direkt zurückspielen könnte.",wraplength=680).pack(anchor="w")
        ttk.Checkbutton(sec,text="Ich verwende für das Ziel BitLocker oder eine NAS-seitige Verschlüsselung / Zugriffsschutz",variable=self.bitlocker_confirm).pack(anchor="w",pady=(8,0))

        self.status=ttk.Label(box,text="Bereit.",wraplength=700); self.status.pack(anchor="w",pady=(8,0))
        row=ttk.Frame(box); row.pack(fill="x",side="bottom",pady=(12,0))
        ttk.Button(row,text="Abbrechen",command=self.destroy).pack(side="right")
        ttk.Button(row,text="▶ Systemabbild jetzt erstellen",command=self.run).pack(side="right",padx=(0,6))
        targets=_targets(self.store)
        if targets:self.target_name.set(targets[0].get("name") or "")

    def manage_target(self):
        add_or_select_target(self.app)
        self.after(200,self.refresh_targets)

    def refresh_targets(self):
        vals=[t.get("name") for t in _targets(self.store)]
        self.target_combo.configure(values=vals)
        t=_target(self.store)
        if t:self.target_name.set(t.get("name") or "")

    def run(self):
        target=next((t for t in _targets(self.store) if t.get("name")==self.target_name.get()),None)
        if not target:
            messagebox.showwarning("Systemabbild","Bitte zuerst ein Zielmedium auswählen.",parent=self); return
        if not self.bitlocker_confirm.get():
            if not messagebox.askyesno("Systemabbild unverschlüsselt auf Zielmedium","Das native Windows-Systemabbild ist nicht durch den PC-Backup-Vault-AES-Container geschützt.\n\nOhne BitLocker/NAS-Schutz könnten Personen mit Zugriff auf das Zielmedium die Image-Dateien sehen. Trotzdem fortfahren?",parent=self):return
        self.status.config(text="Windows-Systemabbild läuft … Administratorrechte sind erforderlich.")
        self.update_idletasks()
        try:
            r=create_system_image(target,self.include_volume.get().strip() or None,quiet=True)
            messagebox.showinfo("Systemabbild","Systemabbild erfolgreich erstellt.\n\n"+recovery_instructions(r.get("target") or target.get("path")),parent=self)
            self.destroy()
        except Exception as e:
            messagebox.showerror("Systemabbild",str(e),parent=self)
            self.status.config(text="Systemabbild fehlgeschlagen – Meldung prüfen.")


def apply_system_image_assistant(AssistantClass):
    original_step_task=AssistantClass.step_task
    original_next=AssistantClass.next

    def step_task(self):
        self.subtitle.configure(text="Schritt 1 von 7 – Was möchten Sie tun?")
        ttk.Label(self.body,text="Was möchten Sie tun?",font=("Segoe UI",14,"bold")).pack(anchor="w",pady=(4,14))
        v=tk.StringVar(value=self.data.get("task","BACKUP"))
        def setv():self.data["task"]=v.get()
        ttk.Radiobutton(self.body,text="Backup erstellen / neuen Backup-Job anlegen",variable=v,value="BACKUP",command=setv).pack(anchor="w",pady=7)
        ttk.Radiobutton(self.body,text="Rücksicherung / Wiederherstellung",variable=v,value="RESTORE",command=setv).pack(anchor="w",pady=7)
        ttk.Radiobutton(self.body,text="Komplettes Windows-Systemabbild (Bare-Metal)",variable=v,value="SYSTEM_IMAGE",command=setv).pack(anchor="w",pady=7)
        ttk.Label(self.body,text="Systemabbild ist für defekte Systemplatten oder eine vollständige Rechner-Wiederherstellung gedacht. Normale KC-/Dateibackups bleiben verschlüsselt im Vault.",wraplength=790).pack(anchor="w",pady=(16,0))

    def next_(self):
        if self.step==0 and self.data.get("task")=="SYSTEM_IMAGE":
            self.destroy(); SystemImageWizard(self.app); return
        return original_next(self)

    AssistantClass.step_task=step_task
    AssistantClass.next=next_
