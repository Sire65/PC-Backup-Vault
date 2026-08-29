from __future__ import annotations

import tkinter as tk
from datetime import date, datetime, time
from tkinter import messagebox, ttk

import kc_backup_scheduler_ui as scheduler_ui
from kc_backup_program_registry import default_registry
from kc_backup_scheduler import BackupScheduleJob, ScheduleAction, ScheduleFrequency


def registered_program_ids() -> tuple[str, ...]:
    return tuple(program.program_id for program in default_registry().all())


class RegisteredProgramJobAssistant(tk.Toplevel):
    def __init__(self, master, *, on_save, default_program_id: str):
        super().__init__(master)
        self.on_save = on_save
        self.allowed_program_ids = registered_program_ids()
        selected = default_program_id if default_program_id in self.allowed_program_ids else self.allowed_program_ids[0]
        self.title("Neuer Backup-Job")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        self.program = tk.StringVar(value=selected)
        self.action = tk.StringVar(value=ScheduleAction.BACKUP.value)
        self.frequency = tk.StringVar(value=ScheduleFrequency.DAILY.value)
        self.start_date = tk.StringVar(value=date.today().strftime("%d.%m.%Y"))
        self.start_time = tk.StringVar(value="02:00")
        self.name = tk.StringVar(value="Automatische Sicherung")
        self._build()

    def _build(self):
        frm = ttk.Frame(self, padding=16)
        frm.pack(fill="both", expand=True)
        fields = [
            ("Programm", ttk.Combobox(frm, textvariable=self.program, state="readonly", values=self.allowed_program_ids, width=31)),
            ("Bezeichnung", ttk.Entry(frm, textvariable=self.name, width=34)),
            ("Job", ttk.Combobox(frm, textvariable=self.action, state="readonly", values=[a.value for a in ScheduleAction], width=31)),
            ("Rhythmus", ttk.Combobox(frm, textvariable=self.frequency, state="readonly", values=[f.value for f in ScheduleFrequency], width=31)),
            ("Startdatum", ttk.Entry(frm, textvariable=self.start_date, width=34)),
            ("Uhrzeit", ttk.Entry(frm, textvariable=self.start_time, width=34)),
        ]
        for row, (label, widget) in enumerate(fields):
            ttk.Label(frm, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=5)
            widget.grid(row=row, column=1, sticky="ew", pady=5)
        ttk.Label(frm, text="Sicherheitsprofil: KC MAXIMUM (fest)").grid(row=len(fields), column=0, columnspan=2, sticky="w", pady=(10, 4))
        buttons = ttk.Frame(frm)
        buttons.grid(row=len(fields)+1, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(buttons, text="Abbrechen", command=self.destroy).pack(side="left", padx=5)
        ttk.Button(buttons, text="Job anlegen", command=self._save).pack(side="left")

    def _save(self):
        try:
            program_id = self.program.get().strip()
            if program_id not in self.allowed_program_ids:
                raise ValueError("Programm ist nicht im Backup-Central-Register freigegeben")
            start_date = datetime.strptime(self.start_date.get().strip(), "%d.%m.%Y").date()
            start_time = datetime.strptime(self.start_time.get().strip(), "%H:%M").time()
            job = BackupScheduleJob(
                program_id=program_id,
                display_name=self.name.get().strip() or "Automatischer Job",
                start_date=start_date,
                start_time=time(start_time.hour, start_time.minute),
                frequency=ScheduleFrequency(self.frequency.get()),
                action=ScheduleAction(self.action.get()),
            )
        except Exception as exc:
            messagebox.showerror("Job anlegen", f"Angaben prüfen:\n{exc}", parent=self)
            return
        self.on_save(job)
        self.destroy()


def enable_scheduler_program_guard(App):
    """Install the guarded assistant without changing calendar/dispatch semantics."""
    if getattr(App, "_kc_scheduler_program_guard_enabled", False):
        return
    scheduler_ui.JobAssistant = RegisteredProgramJobAssistant
    App._kc_scheduler_program_guard_enabled = True
