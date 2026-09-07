from __future__ import annotations

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from storage_v180 import DISPLAY, CODE, _targets, _target, add_or_select_target


class BackupAssistant(tk.Toplevel):
    """Guided assistant for creating backup jobs or starting restore workflow.

    The assistant deliberately writes into the existing ConfigStore plan model.
    It is a usability layer, not a second backup configuration system.
    """

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.store = app.store
        self.title("PC Backup Vault – Assistent")
        self.geometry("880x650")
        self.minsize(820, 600)
        self.transient(app)
        self.grab_set()

        self.step = 0
        self.data = {
            "task": "BACKUP",
            "name": "Mein Backup",
            "paths": [],
            "payload_target": "AUTO",
            "filesystem_target_id": None,
            "backup_mode": "AUTO",
            "verify": True,
            "one_touch": True,
            "schedule_enabled": False,
            "schedule_type": "DAILY",
            "schedule_time": "20:00",
            "weekday": "MON",
            "scheduler_auto_sync": True,
        }

        self.header = ttk.Frame(self, padding=(16, 14, 16, 8))
        self.header.pack(fill="x")
        ttk.Label(self.header, text="🪄 Backup-Assistent", font=("Segoe UI", 18, "bold")).pack(anchor="w")
        self.subtitle = ttk.Label(self.header, text="Ich führe Sie Schritt für Schritt durch die Einrichtung.")
        self.subtitle.pack(anchor="w", pady=(3, 0))

        self.body = ttk.Frame(self, padding=(16, 8, 16, 8))
        self.body.pack(fill="both", expand=True)

        self.footer = ttk.Frame(self, padding=(16, 8, 16, 14))
        self.footer.pack(fill="x")
        self.btn_cancel = ttk.Button(self.footer, text="Abbrechen", command=self.destroy)
        self.btn_cancel.pack(side="left")
        self.btn_back = ttk.Button(self.footer, text="← Zurück", command=self.back)
        self.btn_back.pack(side="right", padx=(6, 0))
        self.btn_next = ttk.Button(self.footer, text="Weiter →", command=self.next)
        self.btn_next.pack(side="right")

        self.render()

    def clear(self):
        for w in self.body.winfo_children():
            w.destroy()

    def render(self):
        self.clear()
        self.btn_back.configure(state="disabled" if self.step == 0 else "normal")
        steps = [
            self.step_task,
            self.step_sources,
            self.step_target,
            self.step_mode,
            self.step_options,
            self.step_schedule,
            self.step_summary,
        ]
        self.step = max(0, min(self.step, len(steps)-1))
        steps[self.step]()

    def next(self):
        if not self.validate_step():
            return
        if self.step >= 6:
            self.finish()
            return
        # Restore needs no backup-job configuration after task choice.
        if self.step == 0 and self.data["task"] == "RESTORE":
            self.finish_restore()
            return
        self.step += 1
        self.render()

    def back(self):
        if self.step > 0:
            self.step -= 1
            self.render()

    def validate_step(self):
        if self.step == 1 and not self.data.get("paths"):
            messagebox.showwarning("Assistent", "Bitte mindestens eine Datei oder einen Ordner als Quelle auswählen.", parent=self)
            return False
        if self.step == 2 and self.data.get("payload_target") == CODE and not self.data.get("filesystem_target_id"):
            messagebox.showwarning("Assistent", "Bitte ein Laufwerk, einen Ordner oder ein NAS-Ziel auswählen.", parent=self)
            return False
        if self.step == 5 and self.data.get("schedule_enabled"):
            try:
                hh, mm = [int(x) for x in self.data.get("schedule_time", "").split(":")]
                if not (0 <= hh <= 23 and 0 <= mm <= 59):
                    raise ValueError
            except Exception:
                messagebox.showwarning("Assistent", "Bitte eine gültige Uhrzeit im Format HH:MM eingeben.", parent=self)
                return False
        return True

    def step_task(self):
        self.subtitle.configure(text="Schritt 1 von 7 – Was möchten Sie tun?")
        ttk.Label(self.body, text="Was möchten Sie tun?", font=("Segoe UI", 14, "bold")).pack(anchor="w", pady=(4, 14))
        v = tk.StringVar(value=self.data["task"])
        def setv(): self.data["task"] = v.get()
        ttk.Radiobutton(self.body, text="Backup erstellen / neuen Backup-Job anlegen", variable=v, value="BACKUP", command=setv).pack(anchor="w", pady=7)
        ttk.Radiobutton(self.body, text="Rücksicherung / Wiederherstellung", variable=v, value="RESTORE", command=setv).pack(anchor="w", pady=7)
        ttk.Label(self.body, text="Bei Backup führt der Assistent durch Quellen, Ziel, Sicherungsart, Verifikation, One-Touch und Zeitplan. Bei Rücksicherung öffnet er den vorhandenen Backup-Explorer.", wraplength=790).pack(anchor="w", pady=(16,0))

    def step_sources(self):
        self.subtitle.configure(text="Schritt 2 von 7 – Quelldaten auswählen")
        ttk.Label(self.body, text="Welche Daten sollen gesichert werden?", font=("Segoe UI", 14, "bold")).pack(anchor="w", pady=(4, 10))
        self.lst_sources = tk.Listbox(self.body, height=16)
        self.lst_sources.pack(fill="both", expand=True)
        for p in self.data.get("paths") or []:
            self.lst_sources.insert("end", p)
        row = ttk.Frame(self.body); row.pack(fill="x", pady=(8,0))
        def add_folder():
            p = filedialog.askdirectory(parent=self, title="Quellordner auswählen")
            if p and p not in self.data["paths"]:
                self.data["paths"].append(p); self.lst_sources.insert("end", p)
        def add_files():
            for p in filedialog.askopenfilenames(parent=self, title="Quelldateien auswählen"):
                if p not in self.data["paths"]:
                    self.data["paths"].append(p); self.lst_sources.insert("end", p)
        def remove():
            for i in reversed(self.lst_sources.curselection()):
                val=self.lst_sources.get(i); self.lst_sources.delete(i)
                try:self.data["paths"].remove(val)
                except ValueError:pass
        ttk.Button(row, text="＋ Ordner", command=add_folder).pack(side="left")
        ttk.Button(row, text="＋ Dateien", command=add_files).pack(side="left", padx=6)
        ttk.Button(row, text="Entfernen", command=remove).pack(side="left")
        ttk.Label(self.body, text="Sie können mehrere Laufwerke, Ordner und einzelne Dateien in einem Job kombinieren.", wraplength=790).pack(anchor="w", pady=(10,0))

    def step_target(self):
        self.subtitle.configure(text="Schritt 3 von 7 – Backup-Ziel")
        ttk.Label(self.body, text="Wohin soll gesichert werden?", font=("Segoe UI", 14, "bold")).pack(anchor="w", pady=(4, 12))
        display_map = {
            "AUTO": "Automatisch (empfohlen)",
            "B2": "Backblaze B2",
            "NEON": "Neon – nur Kleinmengen",
            CODE: DISPLAY,
        }
        reverse = {v:k for k,v in display_map.items()}
        target_var=tk.StringVar(value=display_map.get(self.data.get("payload_target"), "Automatisch (empfohlen)"))
        combo=ttk.Combobox(self.body, textvariable=target_var, state="readonly", values=list(reverse.keys()), width=52)
        combo.pack(anchor="w")
        fs_label=ttk.Label(self.body, text="")
        fs_label.pack(anchor="w", pady=(12,4))
        def refresh_fs():
            tid=self.data.get("filesystem_target_id"); t=_target(self.store,tid)
            fs_label.configure(text=f"Gewähltes Dateisystem-Ziel: {(t or {}).get('name','–')}  {(t or {}).get('path','')}")
        def choose_fs():
            add_or_select_target(self.app)
            self.after(150, pick_active)
        def pick_active():
            t=_target(self.store)
            if t:
                self.data["filesystem_target_id"]=t.get("id"); target_var.set(DISPLAY); self.data["payload_target"]=CODE
                refresh_fs()
        def changed(_=None):
            self.data["payload_target"]=reverse.get(target_var.get(),"AUTO")
            refresh_fs()
        combo.bind("<<ComboboxSelected>>", changed)
        ttk.Button(self.body, text="📁 Laufwerk / Ordner / NAS auswählen …", command=choose_fs).pack(anchor="w", pady=(4,0))
        refresh_fs()
        ttk.Label(self.body, text="Für USB, externe Festplatten/SSD und NAS wird das konkrete Ziel fest mit dem Job gespeichert.", wraplength=790).pack(anchor="w", pady=(12,0))

    def step_mode(self):
        self.subtitle.configure(text="Schritt 4 von 7 – Sicherungsart")
        ttk.Label(self.body, text="Welche Sicherungsart möchten Sie?", font=("Segoe UI", 14, "bold")).pack(anchor="w", pady=(4, 12))
        v=tk.StringVar(value=self.data.get("backup_mode","AUTO"))
        items=[
            ("AUTO","Automatisch (empfohlen)","Das Programm entscheidet anhand des letzten Sicherungsstands."),
            ("INCREMENTAL","Inkrementell","Nur neue oder geänderte Daten werden zusätzlich gespeichert."),
            ("FULL","Vollständig","Alle ausgewählten Daten werden vollständig geprüft und neu gesichert."),
            ("QUICK","Schnell","Schnelle Prüfung anhand vorhandener Metadaten, wenn ein aktueller Vollstand existiert."),
        ]
        for code,label,desc in items:
            line=ttk.Frame(self.body); line.pack(fill="x", pady=5)
            ttk.Radiobutton(line,text=label,variable=v,value=code,command=lambda:self.data.update(backup_mode=v.get())).pack(anchor="w")
            ttk.Label(line,text=desc,wraplength=760).pack(anchor="w",padx=(22,0))

    def step_options(self):
        self.subtitle.configure(text="Schritt 5 von 7 – Optionen")
        ttk.Label(self.body, text="Welche Zusatzfunktionen sollen aktiv sein?", font=("Segoe UI", 14, "bold")).pack(anchor="w", pady=(4,12))
        verify=tk.BooleanVar(value=bool(self.data.get("verify",True)))
        one=tk.BooleanVar(value=bool(self.data.get("one_touch",True)))
        schedule=tk.BooleanVar(value=bool(self.data.get("schedule_enabled",False)))
        def sync():
            self.data["verify"]=verify.get(); self.data["one_touch"]=one.get(); self.data["schedule_enabled"]=schedule.get()
        ttk.Checkbutton(self.body,text="Nach dem Backup automatisch verifizieren",variable=verify,command=sync).pack(anchor="w",pady=7)
        ttk.Checkbutton(self.body,text="Als One-Touch-Job verfügbar machen",variable=one,command=sync).pack(anchor="w",pady=7)
        ttk.Checkbutton(self.body,text="Zusätzlich automatisch nach Zeitplan ausführen",variable=schedule,command=sync).pack(anchor="w",pady=7)
        ttk.Label(self.body,text="So bleiben die Funktionen Optionen innerhalb eines Jobs; es werden keine zusätzlichen großen Schaltflächen benötigt.",wraplength=790).pack(anchor="w",pady=(14,0))

    def step_schedule(self):
        self.subtitle.configure(text="Schritt 6 von 7 – Zeitplan")
        ttk.Label(self.body, text="Zeitplan", font=("Segoe UI", 14, "bold")).pack(anchor="w", pady=(4,12))
        if not self.data.get("schedule_enabled"):
            ttk.Label(self.body,text="Kein automatischer Zeitplan gewählt. Der Job kann später jederzeit im Job-Editor geplant werden.",wraplength=790).pack(anchor="w")
            return
        type_display={"DAILY":"Täglich","WEEKLY":"Wöchentlich","ONLOGON":"Bei Windows-Anmeldung"}
        rev={v:k for k,v in type_display.items()}
        typ=tk.StringVar(value=type_display.get(self.data.get("schedule_type"),"Täglich"))
        t=ttk.Combobox(self.body,textvariable=typ,state="readonly",values=list(rev.keys()),width=30); t.pack(anchor="w")
        ttk.Label(self.body,text="Uhrzeit (HH:MM)").pack(anchor="w",pady=(12,3))
        timev=tk.StringVar(value=self.data.get("schedule_time","20:00")); ttk.Entry(self.body,textvariable=timev,width=12).pack(anchor="w")
        ttk.Label(self.body,text="Wochentag (nur bei wöchentlich)").pack(anchor="w",pady=(12,3))
        days={"MON":"Montag","TUE":"Dienstag","WED":"Mittwoch","THU":"Donnerstag","FRI":"Freitag","SAT":"Samstag","SUN":"Sonntag"}; drev={v:k for k,v in days.items()}
        dayv=tk.StringVar(value=days.get(self.data.get("weekday"),"Montag")); ttk.Combobox(self.body,textvariable=dayv,state="readonly",values=list(drev.keys()),width=20).pack(anchor="w")
        def sync(*_):
            self.data["schedule_type"]=rev.get(typ.get(),"DAILY"); self.data["schedule_time"]=timev.get().strip(); self.data["weekday"]=drev.get(dayv.get(),"MON")
        typ.trace_add("write",sync); timev.trace_add("write",sync); dayv.trace_add("write",sync); sync()

    def step_summary(self):
        self.subtitle.configure(text="Schritt 7 von 7 – Prüfen und speichern")
        ttk.Label(self.body,text="Zusammenfassung",font=("Segoe UI",14,"bold")).pack(anchor="w",pady=(4,12))
        namev=tk.StringVar(value=self.data.get("name") or "Mein Backup")
        ttk.Label(self.body,text="Name des Jobs").pack(anchor="w")
        ttk.Entry(self.body,textvariable=namev,width=48).pack(anchor="w",pady=(3,12))
        def sync(*_):self.data["name"]=namev.get().strip() or "Mein Backup"
        namev.trace_add("write",sync); sync()
        t=_target(self.store,self.data.get("filesystem_target_id")) if self.data.get("payload_target")==CODE else None
        target=(t or {}).get("name") if t else self.data.get("payload_target")
        schedule="manuell"
        if self.data.get("schedule_enabled"):
            schedule=self.data.get("schedule_type")
            if schedule in ("DAILY","WEEKLY"):schedule += f" {self.data.get('schedule_time')}"
        text=(f"Quellen: {len(self.data.get('paths') or [])}\n"
              f"Ziel: {target}\n"
              f"Sicherungsart: {self.data.get('backup_mode')}\n"
              f"Verifikation: {'Ja' if self.data.get('verify') else 'Nein'}\n"
              f"One-Touch: {'Ja' if self.data.get('one_touch') else 'Nein'}\n"
              f"Zeitplan: {schedule}")
        ttk.Label(self.body,text=text,justify="left",wraplength=790).pack(anchor="w")
        self.btn_next.configure(text="✓ Job speichern")

    def finish(self):
        profile_id=self.store.data.get("active_profile_id")
        plan={
            "name": self.data.get("name") or "Mein Backup",
            "paths": list(self.data.get("paths") or []),
            "profile_id": profile_id,
            "enabled": bool(self.data.get("one_touch",True) or self.data.get("schedule_enabled",False)),
            "schedule_type": self.data.get("schedule_type","DAILY") if self.data.get("schedule_enabled") else "MANUAL",
            "schedule_time": self.data.get("schedule_time","20:00"),
            "weekday": self.data.get("weekday","MON"),
            "payload_target": self.data.get("payload_target","AUTO"),
            "filesystem_target_id": self.data.get("filesystem_target_id"),
            "backup_mode": self.data.get("backup_mode","AUTO"),
            "auto_verify": bool(self.data.get("verify",True)),
            "scheduler_auto_sync": bool(self.data.get("schedule_enabled",False)),
            "assistant_created": True,
        }
        pid=self.store.add_plan(plan)
        # add_plan normalizes only known legacy fields, therefore persist 1.8 additions explicitly.
        self.store.update_plan(pid,{k:v for k,v in plan.items() if k not in {"id"}})
        if self.data.get("one_touch",True):
            self.store.set_default_plan(pid)
        # Use the existing settings window scheduler path to keep one implementation of task creation.
        if self.data.get("schedule_enabled"):
            try:
                from scheduler import install_task
                ok,msg=install_task(self.store.get_plan(pid))
                if not ok:
                    messagebox.showwarning("Assistent",f"Job wurde gespeichert, aber der Windows-Scheduler konnte nicht eingerichtet werden:\n\n{msg}",parent=self)
            except Exception as e:
                messagebox.showwarning("Assistent",f"Job wurde gespeichert, Scheduler-Einrichtung fehlgeschlagen:\n\n{e}",parent=self)
        messagebox.showinfo("Assistent",f"Der Backup-Job '{plan['name']}' wurde angelegt.",parent=self)
        try:self.app.refresh_status()
        except Exception:pass
        self.destroy()

    def finish_restore(self):
        self.destroy()
        try:
            self.app.open_explorer()
        except Exception as e:
            messagebox.showerror("Rücksicherung",str(e),parent=self.app)


def apply_assistant_v180(AppClass):
    original_build=AppClass._build
    def _build(self):
        original_build(self)
        # Put wizard in top command bar near Settings; do not create many specialized buttons.
        top_candidates=[w for w in self.winfo_children() if isinstance(w,ttk.Frame)]
        parent=top_candidates[0] if top_candidates else self
        self.btn_assistant_v180=ttk.Button(parent,text="🪄 Assistent",command=lambda:BackupAssistant(self))
        try:self.btn_assistant_v180.pack(side="right",padx=(0,6),before=parent.winfo_children()[-1])
        except Exception:self.btn_assistant_v180.pack(side="right",padx=(0,6))
    AppClass._build=_build
