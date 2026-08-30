from __future__ import annotations

from datetime import datetime

from backup_engine import collect_paths
from kc_backup_job_store import load_jobs_resilient
from kc_backup_program_registry import default_registry, resolve_program_scope
from kc_backup_program_status import record_program_failure
from kc_backup_program_store import load_program_registry
from kc_backup_scheduler import ScheduleAction
from kc_backup_scheduler_control import load_scheduler_control
from kc_backup_scheduler_runtime import claim_dispatch, due_dispatches


def enable_scheduler_hardening(App):
    """Replace only unattended tick dispatch with fail-safe control and resilient reads."""
    if getattr(App, "_kc_scheduler_hardening_enabled", False):
        return
    if not getattr(App, "_kc_backup_central_enabled", False):
        raise RuntimeError("Backup Central muss vor Scheduler-Hardening aktiviert werden")

    original_tick = App._kc_scheduler_tick

    def _scheduler_control_path(self):
        return self.store.path.parent / "KC_BACKUP_SCHEDULER_CONTROL.json"

    def hardened_tick(self):
        try:
            if getattr(self, "_backup_running", False):
                return

            control = load_scheduler_control(self._kc_scheduler_control_path())
            if not control.enabled:
                return

            result = load_jobs_resilient(self._kc_scheduler_path())
            if result.warnings:
                signature = " | ".join(result.warnings)
                if signature != getattr(self, "_kc_scheduler_warning_signature", None):
                    self._kc_scheduler_warning_signature = signature
                    try:
                        self.notify_kc(
                            "backup_scheduler_warning",
                            "Backup-Scheduler Jobdatei teilweise beschädigt",
                            signature,
                            "WARN",
                        )
                    except Exception:
                        pass

            jobs = list(result.jobs)
            now = datetime.now().astimezone()
            for dispatch in due_dispatches(jobs, now=now):
                if not claim_dispatch(self._kc_scheduler_runtime_path(), dispatch, now=now):
                    continue

                if dispatch.action == ScheduleAction.BACKUP:
                    try:
                        registry = load_program_registry(self._kc_program_store_path(), default_registry())
                        program = registry.get(dispatch.program_id)
                        scope = resolve_program_scope(program)
                    except Exception as exc:
                        self._kc_finish_scheduled(dispatch, "BLOCKED", f"Programm nicht sicher auflösbar: {exc}")
                        continue
                    if not scope.ready:
                        reason = "; ".join(scope.blockers) or "Sicherungsumfang nicht bereit"
                        self._kc_finish_scheduled(dispatch, "BLOCKED", reason)
                        try:
                            record_program_failure(self._kc_program_status_path(), program_id=dispatch.program_id, error=reason)
                        except Exception:
                            pass
                        continue
                    self.selected = collect_paths([str(path) for path in scope.paths])
                    self._refresh_tree()
                    self.update_backup_recommendation()
                    self._update_backup_button_state()
                    self.run_default_one_touch(program_id=dispatch.program_id, scheduler_dispatch=dispatch)
                    break

                if dispatch.action == ScheduleAction.VERIFY:
                    self._kc_run_scheduled_verify(dispatch)
                    break
        except Exception as exc:
            try:
                self.notify_kc("backup_scheduler_error", "Backup-Scheduler Fehler", str(exc), "ERROR")
            except Exception:
                pass
        finally:
            try:
                self.after(60_000, self._kc_scheduler_tick)
            except Exception:
                pass

    App._kc_scheduler_control_path = _scheduler_control_path
    App._kc_scheduler_tick_original = original_tick
    App._kc_scheduler_tick = hardened_tick
    App._kc_scheduler_hardening_enabled = True
