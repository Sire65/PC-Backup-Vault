from __future__ import annotations

import calendar
import tkinter as tk
from datetime import date, datetime, time
from tkinter import messagebox, ttk
from typing import Callable, Iterable

from kc_backup_scheduler import (
    BackupExperience,
    BackupScheduleJob,
    OneTouchBackupPlan,
    ScheduleAction,
    ScheduleFrequency,
    build_calendar,
    default_recurring_jobs,
)


ACTION_LABELS = {
    ScheduleAction.BACKUP: "Sicherung",
    ScheduleAction.VERIFY: "Vollprüfung",
    ScheduleAction.RESTORE_TEST: "Restore-Test",
}
FREQUENCY_LABELS = {
    ScheduleFrequency.ONCE: "Einmalig",
    ScheduleFrequency.DAILY: "Täglich",
    ScheduleFrequency.WEEKLY: "Wöchentlich",
    ScheduleFrequency.MONTHLY: "Monatlich",
}


class SchedulerModel:
    """In-memory scheduler state for the first UI integration stage.

    It deliberately does not execute jobs. Persisting and dispatching are separate
    integration steps so opening the calendar can never start a backup by accident.
    """

    def __init__(self, jobs: Iterable[BackupScheduleJob] = ()):
        self.jobs = list(jobs)

    def add(self, job: BackupScheduleJob) -> None:
        self.jobs.append(job)

    def remove(self, job_id: str) -> None:
        self.jobs = [job for job in self.jobs if job.job_id != job_id]

    def set_enabled(self, job_id: str, enabled: bool) -> None:
        for job in self.jobs:
            if job.job_id == job_id:
                job.enabled = bool(enabled)
                return
        raise KeyError(job_id)

    def calendar_entries(self, year: int, month: int):
        first = date(year, month, 1)
        last = date(year, month, calendar.monthrange(year, month)[1])
        return build_calendar(self.jobs, first, last)


class BackupSchedulerWindow(tk.Toplevel):
    """Simple-first calendar and job assistant for Backup Central.

    on_one_touch receives a OneTouchBackupPlan only after the user presses the
    explicit button. No backup engine is imported or called by this window.
    """

    def __init__(
        self,
        master,
        *,
        program_id: str = "pc-backup-vault",
        jobs: Iterable[BackupScheduleJob] = (),
        on_one_touch: Callable[[OneTouchBackupPlan], None] | None = None,
    ):
        super().__init__(master)
        self.program_id = program_id
        self.model = SchedulerModel(jobs or default_recurring_jobs(program_id))
        self.on_one_touch = on_one_touch
        today = date.today()
        self.year = today.year
        self.month = today.month
        self.experience = tk.StringVar(value=BackupExperience.SIMPLE.value)
        self.title("Backup Central – Kalender & Jobs")
        self.geometry("1240x820")
        self.minsize(980, 680)
        self._build()
        self.refresh()

    def _build(self):
        head = ttk.Frame(self, padding=12)
        head.pack(fill="x")
        ttk.Label(head, text="Backup Central", font=("Segoe UI", 18, "bold")).pack(side="left")
        ttk.Label(head, text="Einfach sichern · Jobs planen · Kalender prüfen").pack(side="left", padx=16)
        ttk.Combobox(
            head,
            state="readonly",
            width=12,
            textvariable=self.experience,
            values=[item.value for item in BackupExperience],
        ).pack(side="right")

        one = ttk.LabelFrame(self, text="One-Touch", padding=12)
        one.pack(fill="x", padx=12, pady=(0, 10))
        ttk.Button(one, text="Jetzt sicher sichern", command=self._one_touch).pack(side="left")
        ttk.Label(
            one,
            text="Probelauf → Sicherung → Vollprüfung → Sicherungspunkt → Protokoll",
        ).pack(side="left", padx=16)

        toolbar = ttk.Frame(self, padding=(12, 2))
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="‹", width=4, command=lambda: self._move_month(-1)).pack(side="left")
        self.month_label = ttk.Label(toolbar, font=("Segoe UI", 13, "bold"))
        self.month_label.pack(side="left", padx=10)
        ttk.Button(toolbar, text="›", width=4, command=lambda: self._move_month(1)).pack(side="left")
        ttk.Button(toolbar, text="Neuer Job", command=self._new_job).pack(side="right")

        body = ttk.Panedwindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, padx=12, pady=8)
        self.cal = ttk.Frame(body, padding=6)
        self.jobs_frame = ttk.Frame(body, padding=6)
        body.add(self.cal, weight=3)
        body.add(self.jobs_frame, weight=2)

        self.job_tree = ttk.Treeview(
            self.jobs_frame,
            columns=("enabled", "program", "action", "frequency", "when"),
            show="headings",
            height=18,
        )
        for key, text, width in (
            ("enabled", "Aktiv", 55),
            ("program", "Programm", 130),
            ("action", "Job", 100),
            ("frequency", "Rhythmus", 100),
            ("when", "Start", 120),
        ):
            self.job_tree.heading(key, text=text)
            self.job_tree.column(key, width=width, anchor="w")
        self.job_tree.pack(fill="both", expand=True)
        buttons = ttk.Frame(self.jobs_frame)
        buttons.pack(fill="x", pady=(8, 0))
        ttk.Button(buttons, text="Aktiv/Pause", command=self._toggle_selected).pack(side="left")
        ttk.Button(buttons, text="Entfernen", command=self._remove_selected).pack(side="left", padx=6)

        self.status = ttk.Label(self, text="", padding=(12, 6))
        self.status.pack(fill="x")

    def refresh(self):
        self.month_label.configure(text=f"{calendar.month_name[self.month]} {self.year}")
        self._render_calendar()
        self._render_jobs()
        self.status.configure(text=f"{len(self.model.jobs)} geplante Jobs · keine automatische Ausführung aus dieser Ansicht")

    def _render_calendar(self):
        for child in self.cal.winfo_children():
            child.destroy()
        for col, name in enumerate(("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")):
            ttk.Label(self.cal, text=name, anchor="center", font=("Segoe UI", 9, "bold")).grid(row=0, column=col, sticky="ew", padx=2, pady=2)
            self.cal.columnconfigure(col, weight=1, uniform="day")

        entries = self.model.calendar_entries(self.year, self.month)
        by_day: dict[int, list] = {}
        for entry in entries:
            by_day.setdefault(entry.starts_at.day, []).append(entry)

        weeks = calendar.Calendar(firstweekday=0).monthdayscalendar(self.year, self.month)
        for row, week in enumerate(weeks, start=1):
            self.cal.rowconfigure(row, weight=1, uniform="week")
            for col, day in enumerate(week):
                cell = ttk.LabelFrame(self.cal, text=str(day) if day else "", padding=5)
                cell.grid(row=row, column=col, sticky="nsew", padx=2, pady=2)
                if not day:
                    continue
                for entry in by_day.get(day, [])[:4]:
                    label = f"{entry.starts_at:%H:%M} {ACTION_LABELS[entry.action]}\n{entry.program_id}"
                    ttk.Label(cell, text=label, justify="left").pack(anchor="w", fill="x", pady=1)
                extra = len(by_day.get(day, [])) - 4
                if extra > 0:
                    ttk.Label(cell, text=f"+ {extra} weitere").pack(anchor="w")

    def _render_jobs(self):
        for item in self.job_tree.get_children():
            self.job_tree.delete(item)
        for job in self.model.jobs:
            self.job_tree.insert(
                "",
                "end",
                iid=job.job_id,
                values=(
                    "Ja" if job.enabled else "Pause",
                    job.program_id,
                    ACTION_LABELS[job.action],
                    FREQUENCY_LABELS[job.frequency],
                    f"{job.start_date:%d.%m.%Y} {job.start_time:%H:%M}",
                ),
            )

    def _move_month(self, delta: int):
        absolute = self.year * 12 + (self.month - 1) + delta
        self.year, month0 = divmod(absolute, 12)
        self.month = month0 + 1
        self.refresh()

    def _one_touch(self):
        plan = OneTouchBackupPlan(self.program_id)
        if self.on_one_touch is None:
            messagebox.showinfo(
                "One-Touch",
                "Sicherer Ablauf vorbereitet:\n\n" + "\n".join(f"{i+1}. {step.user_label}" for i, step in enumerate(plan.steps)) +
                "\n\nNoch keine automatische Ausführung in dieser Integrationsstufe.",
                parent=self,
            )
            return
        self.on_one_touch(plan)

    def _selected_job_id(self) -> str | None:
        selection = self.job_tree.selection()
        return selection[0] if selection else None

    def _toggle_selected(self):
        job_id = self._selected_job_id()
        if not job_id:
            return
        job = next(job for job in self.model.jobs if job.job_id == job_id)
        self.model.set_enabled(job_id, not job.enabled)
        self.refresh()

    def _remove_selected(self):
        job_id = self._selected_job_id()
        if not job_id:
            return
        self.model.remove(job_id)
        self.refresh()

    def _new_job(self):
        JobAssistant(self, on_save=self._save_job, default_program_id=self.program_id)

    def _save_job(self, job: BackupScheduleJob):
        self.model.add(job)
        self.refresh()


class JobAssistant(tk.Toplevel):
    def __init__(self, master, *, on_save: Callable[[BackupScheduleJob], None], default_program_id: str):
        super().__init__(master)
        self.on_save = on_save
        self.title("Neuer Backup-Job")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        self.program = tk.StringVar(value=default_program_id)
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
            ("Programm", ttk.Entry(frm, textvariable=self.program, width=34)),
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
            start_date = datetime.strptime(self.start_date.get().strip(), "%d.%m.%Y").date()
            start_time = datetime.strptime(self.start_time.get().strip(), "%H:%M").time()
            frequency = ScheduleFrequency(self.frequency.get())
            action = ScheduleAction(self.action.get())
            job = BackupScheduleJob(
                program_id=self.program.get().strip(),
                display_name=self.name.get().strip() or "Automatischer Job",
                start_date=start_date,
                start_time=time(start_time.hour, start_time.minute),
                frequency=frequency,
                action=action,
            )
        except Exception as exc:
            messagebox.showerror("Job anlegen", f"Angaben prüfen:\n{exc}", parent=self)
            return
        self.on_save(job)
        self.destroy()
