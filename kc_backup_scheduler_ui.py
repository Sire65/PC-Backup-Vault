from __future__ import annotations

import calendar
import tkinter as tk
from datetime import date, datetime, time, timedelta
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
VIEW_DAY = "Tag"
VIEW_WEEK = "Woche"
VIEW_MONTH = "Monat"
VIEW_VALUES = (VIEW_DAY, VIEW_WEEK, VIEW_MONTH)
GERMAN_MONTHS = (
    "", "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
)


def view_window(anchor: date, view: str) -> tuple[date, date]:
    if view == VIEW_DAY:
        return anchor, anchor
    if view == VIEW_WEEK:
        start = anchor - timedelta(days=anchor.weekday())
        return start, start + timedelta(days=6)
    if view == VIEW_MONTH:
        first = anchor.replace(day=1)
        last = anchor.replace(day=calendar.monthrange(anchor.year, anchor.month)[1])
        return first, last
    raise ValueError(f"Unbekannte Kalenderansicht: {view}")


def move_anchor(anchor: date, view: str, delta: int) -> date:
    if view == VIEW_DAY:
        return anchor + timedelta(days=delta)
    if view == VIEW_WEEK:
        return anchor + timedelta(days=7 * delta)
    if view == VIEW_MONTH:
        absolute = anchor.year * 12 + (anchor.month - 1) + delta
        year, month0 = divmod(absolute, 12)
        month = month0 + 1
        day = min(anchor.day, calendar.monthrange(year, month)[1])
        return date(year, month, day)
    raise ValueError(f"Unbekannte Kalenderansicht: {view}")


def experience_permissions(level: BackupExperience | str) -> dict[str, bool]:
    level = level if isinstance(level, BackupExperience) else BackupExperience(level)
    return {
        "edit_jobs": level in {BackupExperience.ADVANCED, BackupExperience.EXPERT},
        "show_job_list": True,
        "show_technical_details": level == BackupExperience.EXPERT,
        "maximum_security_locked": True,
    }


class SchedulerModel:
    """Scheduler state only; displaying the calendar never dispatches a job."""

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

    def calendar_range(self, start: date, end: date):
        return build_calendar(self.jobs, start, end)

    def calendar_entries(self, year: int, month: int):
        first = date(year, month, 1)
        last = date(year, month, calendar.monthrange(year, month)[1])
        return self.calendar_range(first, last)


class BackupSchedulerWindow(tk.Toplevel):
    """Simple-first calendar and job assistant for Backup Central.

    The window never imports or calls the productive backup engine. One-Touch is
    delegated only after an explicit button press.
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
        self.anchor_date = date.today()
        self.experience = tk.StringVar(value=BackupExperience.SIMPLE.value)
        self.view_mode = tk.StringVar(value=VIEW_MONTH)
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
        self.experience_combo = ttk.Combobox(
            head,
            state="readonly",
            width=12,
            textvariable=self.experience,
            values=[item.value for item in BackupExperience],
        )
        self.experience_combo.pack(side="right")
        self.experience_combo.bind("<<ComboboxSelected>>", lambda _e: self._apply_experience())
        ttk.Label(head, text="Bedienebene:").pack(side="right", padx=(0, 6))

        one = ttk.LabelFrame(self, text="One-Touch", padding=12)
        one.pack(fill="x", padx=12, pady=(0, 10))
        ttk.Button(one, text="Jetzt sicher sichern", command=self._one_touch).pack(side="left")
        ttk.Label(one, text="Probelauf → Sicherung → Vollprüfung → Sicherungspunkt → Protokoll").pack(side="left", padx=16)
        ttk.Label(one, text="Sicherheitsprofil: KC MAXIMUM (fest)").pack(side="right")

        toolbar = ttk.Frame(self, padding=(12, 2))
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="‹", width=4, command=lambda: self._move(-1)).pack(side="left")
        self.period_label = ttk.Label(toolbar, font=("Segoe UI", 13, "bold"))
        self.period_label.pack(side="left", padx=10)
        ttk.Button(toolbar, text="›", width=4, command=lambda: self._move(1)).pack(side="left")
        ttk.Button(toolbar, text="Heute", command=self._today).pack(side="left", padx=(8, 0))

        self.view_combo = ttk.Combobox(toolbar, state="readonly", width=10, textvariable=self.view_mode, values=VIEW_VALUES)
        self.view_combo.pack(side="right", padx=(8, 0))
        self.view_combo.bind("<<ComboboxSelected>>", lambda _e: self.refresh())
        ttk.Label(toolbar, text="Ansicht:").pack(side="right")
        self.btn_new_job = ttk.Button(toolbar, text="Neuer Job", command=self._new_job)
        self.btn_new_job.pack(side="right", padx=(0, 14))

        body = ttk.Panedwindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, padx=12, pady=8)
        self.cal = ttk.Frame(body, padding=6)
        self.jobs_frame = ttk.Frame(body, padding=6)
        body.add(self.cal, weight=3)
        body.add(self.jobs_frame, weight=2)

        self.job_tree = ttk.Treeview(
            self.jobs_frame,
            columns=("enabled", "program", "action", "frequency", "when", "security"),
            show="headings",
            height=18,
        )
        for key, text, width in (
            ("enabled", "Aktiv", 55),
            ("program", "Programm", 120),
            ("action", "Job", 95),
            ("frequency", "Rhythmus", 95),
            ("when", "Start", 120),
            ("security", "Sicherheit", 85),
        ):
            self.job_tree.heading(key, text=text)
            self.job_tree.column(key, width=width, anchor="w")
        self.job_tree.pack(fill="both", expand=True)
        self.job_tree.bind("<<TreeviewSelect>>", lambda _e: self._render_expert_detail())

        buttons = ttk.Frame(self.jobs_frame)
        buttons.pack(fill="x", pady=(8, 0))
        self.btn_toggle = ttk.Button(buttons, text="Aktiv/Pause", command=self._toggle_selected)
        self.btn_toggle.pack(side="left")
        self.btn_remove = ttk.Button(buttons, text="Entfernen", command=self._remove_selected)
        self.btn_remove.pack(side="left", padx=6)
        self.expert_detail = ttk.Label(self.jobs_frame, text="", wraplength=420)
        self.expert_detail.pack(fill="x", pady=(8, 0))

        self.status = ttk.Label(self, text="", padding=(12, 6))
        self.status.pack(fill="x")

    def refresh(self):
        self._update_period_label()
        self._render_calendar()
        self._render_jobs()
        self._apply_experience()

    def _update_period_label(self):
        start, end = view_window(self.anchor_date, self.view_mode.get())
        if start == end:
            text = f"{start:%d.%m.%Y}"
        elif self.view_mode.get() == VIEW_WEEK:
            text = f"{start:%d.%m.%Y} – {end:%d.%m.%Y}"
        else:
            text = f"{GERMAN_MONTHS[start.month]} {start.year}"
        self.period_label.configure(text=text)

    def _render_calendar(self):
        for child in self.cal.winfo_children():
            child.destroy()
        start, end = view_window(self.anchor_date, self.view_mode.get())
        entries = self.model.calendar_range(start, end)
        if self.view_mode.get() == VIEW_DAY:
            self._render_day(start, entries)
        elif self.view_mode.get() == VIEW_WEEK:
            self._render_week(start, entries)
        else:
            self._render_month(start, entries)

    def _entry_text(self, entry, *, include_date=False):
        prefix = f"{entry.starts_at:%d.%m.} " if include_date else ""
        return f"{prefix}{entry.starts_at:%H:%M}  {ACTION_LABELS[entry.action]}\n{entry.program_id}"

    def _render_day(self, day: date, entries):
        ttk.Label(self.cal, text=f"{day:%A, %d.%m.%Y}", font=("Segoe UI", 12, "bold")).pack(anchor="w", pady=(0, 8))
        if not entries:
            ttk.Label(self.cal, text="Keine geplanten Jobs an diesem Tag.").pack(anchor="w")
            return
        for entry in entries:
            box = ttk.LabelFrame(self.cal, text=f"{entry.starts_at:%H:%M} · {ACTION_LABELS[entry.action]}", padding=8)
            box.pack(fill="x", pady=3)
            ttk.Label(box, text=f"{entry.display_name}\nProgramm: {entry.program_id}").pack(anchor="w")

    def _render_week(self, monday: date, entries):
        by_date: dict[date, list] = {}
        for entry in entries:
            by_date.setdefault(entry.starts_at.date(), []).append(entry)
        for col in range(7):
            day = monday + timedelta(days=col)
            self.cal.columnconfigure(col, weight=1, uniform="weekday")
            cell = ttk.LabelFrame(self.cal, text=f"{('Mo','Di','Mi','Do','Fr','Sa','So')[col]} {day:%d.%m.}", padding=5)
            cell.grid(row=0, column=col, sticky="nsew", padx=2, pady=2)
            for entry in by_date.get(day, []):
                ttk.Label(cell, text=self._entry_text(entry), justify="left", wraplength=135).pack(anchor="w", fill="x", pady=2)
        self.cal.rowconfigure(0, weight=1)

    def _render_month(self, first: date, entries):
        for col, name in enumerate(("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")):
            ttk.Label(self.cal, text=name, anchor="center", font=("Segoe UI", 9, "bold")).grid(row=0, column=col, sticky="ew", padx=2, pady=2)
            self.cal.columnconfigure(col, weight=1, uniform="day")
        by_day: dict[int, list] = {}
        for entry in entries:
            by_day.setdefault(entry.starts_at.day, []).append(entry)
        weeks = calendar.Calendar(firstweekday=0).monthdayscalendar(first.year, first.month)
        for row, week in enumerate(weeks, start=1):
            self.cal.rowconfigure(row, weight=1, uniform="week")
            for col, day in enumerate(week):
                cell = ttk.LabelFrame(self.cal, text=str(day) if day else "", padding=5)
                cell.grid(row=row, column=col, sticky="nsew", padx=2, pady=2)
                if not day:
                    continue
                for entry in by_day.get(day, [])[:4]:
                    ttk.Label(cell, text=self._entry_text(entry), justify="left").pack(anchor="w", fill="x", pady=1)
                extra = len(by_day.get(day, [])) - 4
                if extra > 0:
                    ttk.Label(cell, text=f"+ {extra} weitere").pack(anchor="w")

    def _render_jobs(self):
        self.job_tree.delete(*self.job_tree.get_children())
        for job in self.model.jobs:
            self.job_tree.insert(
                "", "end", iid=job.job_id,
                values=(
                    "Ja" if job.enabled else "Pause",
                    job.program_id,
                    ACTION_LABELS[job.action],
                    FREQUENCY_LABELS[job.frequency],
                    f"{job.start_date:%d.%m.%Y} {job.start_time:%H:%M}",
                    job.profile.security_level,
                ),
            )
        self._render_expert_detail()

    def _apply_experience(self):
        permissions = experience_permissions(self.experience.get())
        state = "normal" if permissions["edit_jobs"] else "disabled"
        self.btn_new_job.configure(state=state)
        self.btn_toggle.configure(state=state)
        self.btn_remove.configure(state=state)
        if permissions["show_technical_details"]:
            self.expert_detail.pack(fill="x", pady=(8, 0))
        else:
            self.expert_detail.pack_forget()
        level = BackupExperience(self.experience.get())
        if level == BackupExperience.SIMPLE:
            hint = "SIMPLE: One-Touch und Kalender · Jobänderungen sind geschützt."
        elif level == BackupExperience.ADVANCED:
            hint = "ADVANCED: Scheduler bearbeiten · Sicherheitsprofil KC MAXIMUM bleibt fest."
        else:
            hint = "EXPERT: technische Jobdetails sichtbar · Sicherheitsgrenzen bleiben fest."
        self.status.configure(text=f"{len(self.model.jobs)} geplante Jobs · {hint} · keine automatische Ausführung aus dieser Ansicht")
        self._render_expert_detail()

    def _render_expert_detail(self):
        if self.experience.get() != BackupExperience.EXPERT.value:
            return
        job_id = self._selected_job_id()
        if not job_id:
            self.expert_detail.configure(text="EXPERT: Job auswählen für technische Details.")
            return
        job = next((item for item in self.model.jobs if item.job_id == job_id), None)
        if not job:
            return
        self.expert_detail.configure(
            text=f"Job-ID: {job.job_id} · Action: {job.action.value} · Frequency: {job.frequency.value} · "
                 f"Security: {job.profile.security_level} · Silent Restore: {'JA' if job.profile.allow_silent_restore else 'NEIN'}"
        )

    def _move(self, delta: int):
        self.anchor_date = move_anchor(self.anchor_date, self.view_mode.get(), delta)
        self.refresh()

    def _move_month(self, delta: int):
        self.anchor_date = move_anchor(self.anchor_date, VIEW_MONTH, delta)
        self.refresh()

    def _today(self):
        self.anchor_date = date.today()
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
        if not experience_permissions(self.experience.get())["edit_jobs"]:
            return
        job_id = self._selected_job_id()
        if not job_id:
            return
        job = next(job for job in self.model.jobs if job.job_id == job_id)
        self.model.set_enabled(job_id, not job.enabled)
        self.refresh()

    def _remove_selected(self):
        if not experience_permissions(self.experience.get())["edit_jobs"]:
            return
        job_id = self._selected_job_id()
        if not job_id:
            return
        self.model.remove(job_id)
        self.refresh()

    def _new_job(self):
        if not experience_permissions(self.experience.get())["edit_jobs"]:
            return
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
