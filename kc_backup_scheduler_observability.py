from __future__ import annotations

from datetime import datetime, timedelta
from tkinter import messagebox, ttk

from kc_backup_job_store import load_jobs
from kc_backup_scheduler_runtime import due_dispatches, record_scheduler_tick, runtime_summary


HEARTBEAT_STALE_AFTER = timedelta(minutes=3)


def _find_button_by_text(root, text: str):
    stack = list(root.winfo_children())
    while stack:
        widget = stack.pop(0)
        try:
            if isinstance(widget, ttk.Button) and str(widget.cget("text")) == text:
                return widget
        except Exception:
            pass
        try:
            stack.extend(widget.winfo_children())
        except Exception:
            pass
    return None


def scheduler_indicator(summary, *, now: datetime) -> tuple[str, str]:
    """Map runtime telemetry to a compact, read-only operator indication."""
    if not summary.last_tick_at:
        return "STARTET", "Noch kein Scheduler-Heartbeat vorhanden"
    try:
        tick = datetime.fromisoformat(summary.last_tick_at)
        age = now.replace(tzinfo=None) - tick
    except Exception:
        return "FEHLER", "Scheduler-Heartbeat ist unlesbar"
    if age > HEARTBEAT_STALE_AFTER:
        return "FEHLER", "Scheduler-Heartbeat ist veraltet"
    if summary.paused_reason:
        return "PAUSIERT", summary.paused_reason
    return "LÄUFT", "Scheduler prüft regelmäßig auf fällige Jobs"


def format_scheduler_details(summary, *, now: datetime) -> str:
    state, reason = scheduler_indicator(summary, now=now)

    def fmt(value: str | None) -> str:
        if not value:
            return "–"
        try:
            return datetime.fromisoformat(value).strftime("%d.%m.%Y %H:%M:%S")
        except Exception:
            return str(value)

    lines = [
        f"Status: {state}",
        f"Hinweis: {reason}",
        f"Letzter Tick: {fmt(summary.last_tick_at)}",
        f"Aktuell im Nachholfenster fällig: {summary.due_count}",
        "",
        f"Letzter Start: {fmt(summary.last_started_at)} · {summary.last_started_program or '–'}",
        f"Letzter Erfolg: {fmt(summary.last_success_at)} · {summary.last_success_program or '–'}",
        f"Letzter BLOCKED: {fmt(summary.last_blocked_at)} · {summary.last_blocked_program or '–'}",
    ]
    if summary.last_blocked_message:
        lines.append(f"  Grund: {summary.last_blocked_message}")
    lines.append(f"Letzter Fehler: {fmt(summary.last_failed_at)} · {summary.last_failed_program or '–'}")
    if summary.last_failed_message:
        lines.append(f"  Grund: {summary.last_failed_message}")
    lines.extend([
        "",
        "Nachholregel: maximal 6 Stunden; ältere Termine werden nicht überraschend ausgeführt.",
        "Restore-Tests werden niemals unbeaufsichtigt automatisch gestartet.",
    ])
    return "\n".join(lines)


def enable_scheduler_observability(App):
    """Add scheduler heartbeat/status UI without changing dispatch decisions."""
    if getattr(App, "_kc_scheduler_observability_enabled", False):
        return
    if not getattr(App, "_kc_backup_central_enabled", False):
        raise RuntimeError("Backup Central muss vor Scheduler-Observability aktiviert werden")

    original_build = App._build
    original_tick = App._kc_scheduler_tick

    def _refresh_scheduler_indicator(self):
        button = getattr(self, "btn_scheduler_runtime", None)
        if button is None:
            return
        try:
            summary = runtime_summary(self._kc_scheduler_runtime_path())
            state, _reason = scheduler_indicator(summary, now=datetime.now().astimezone())
            prefix = {"LÄUFT": "●", "PAUSIERT": "Ⅱ", "FEHLER": "!", "STARTET": "…"}.get(state, "•")
            button.config(text=f"{prefix} Scheduler: {state}")
        except Exception:
            button.config(text="! Scheduler: FEHLER")

    def _show_scheduler_status(self):
        try:
            summary = runtime_summary(self._kc_scheduler_runtime_path())
            text = format_scheduler_details(summary, now=datetime.now().astimezone())
        except Exception as exc:
            text = f"Scheduler-Status konnte nicht sicher gelesen werden.\n\n{exc}"
        messagebox.showinfo("Backup Central – Scheduler-Status", text, parent=self)

    def scheduler_tick_with_observability(self):
        now = datetime.now().astimezone()
        paused_reason = None
        due_count = 0
        try:
            if getattr(self, "_backup_running", False):
                paused_reason = "Eine Sicherung/Vollprüfung läuft; Scheduler wartet auf freien Backup-Kern"
            else:
                jobs = load_jobs(self._kc_scheduler_path())
                due_count = len(due_dispatches(jobs, now=now))
            record_scheduler_tick(
                self._kc_scheduler_runtime_path(),
                now=now,
                paused_reason=paused_reason,
                due_count=due_count,
            )
        except Exception as exc:
            try:
                record_scheduler_tick(
                    self._kc_scheduler_runtime_path(),
                    now=now,
                    paused_reason=f"Statusprüfung fehlerhaft: {exc}",
                    due_count=0,
                )
            except Exception:
                pass
        try:
            return original_tick(self)
        finally:
            try:
                self.after(0, self._kc_refresh_scheduler_indicator)
            except Exception:
                pass

    def build_with_scheduler_observability(self):
        original_build(self)
        status_button = _find_button_by_text(self, "↻ Status")
        if status_button is not None:
            button = ttk.Button(
                status_button.master,
                text="… Scheduler: STARTET",
                command=self._kc_show_scheduler_status,
            )
            button.pack(side="right", padx=(0, 8))
            self.btn_scheduler_runtime = button
            self.after(0, self._kc_refresh_scheduler_indicator)

    App._kc_refresh_scheduler_indicator = _refresh_scheduler_indicator
    App._kc_show_scheduler_status = _show_scheduler_status
    App._kc_scheduler_tick = scheduler_tick_with_observability
    App._build = build_with_scheduler_observability
    App._kc_scheduler_observability_enabled = True
