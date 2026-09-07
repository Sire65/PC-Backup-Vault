from __future__ import annotations

import threading
from tkinter import messagebox

from backup_engine import BackupCancelled
from plan_runner import run_plan


def apply_ui_clarity_fix_v182(AppClass, ui_module):
    """Make assistant backup completion unambiguous and avoid invalid DB reports for filesystem jobs."""

    def run_assistant_plan_now_v180(self, plan_id, plan_name="Backup-Job"):
        if getattr(self, "_backup_running", False):
            messagebox.showwarning(
                "PC Backup Vault",
                "Es läuft bereits eine Sicherung. Der neue Job wurde gespeichert, aber nicht parallel gestartet.",
                parent=self,
            )
            return

        plan = self.store.get_plan(plan_id)
        if not plan:
            messagebox.showerror("PC Backup Vault", "Der gerade angelegte Job wurde nicht gefunden.", parent=self)
            return

        payload_target = str(plan.get("payload_target") or "AUTO").upper()

        try:
            self._reset_live_progress()
            control = self._begin_backup_control()
        except Exception as exc:
            messagebox.showerror("PC Backup Vault", str(exc), parent=self)
            return

        self.lbl_progress.configure(text=f"Assistent-Job '{plan_name}' startet …")

        def cb(done, total, msg, metrics=None):
            self.after(0, lambda: self._progress(done, total, msg, metrics))

        def finish_ui(text):
            try:
                self.lbl_progress.configure(text=text)
            except Exception:
                pass
            try:
                self._set_backup_running(False)
            except Exception:
                try:
                    self._finish_backup_control()
                except Exception:
                    pass
            try:
                self.refresh_status()
                self.refresh_system_status()
            except Exception:
                pass

        def work():
            try:
                result = run_plan(plan_id, cb, control=control)
                job_id = result.get("job_id") if isinstance(result, dict) else None

                def success():
                    finish_ui(f"Assistent-Job '{plan_name}' erfolgreich abgeschlossen.")

                    # Filesystem jobs use their own manifest under .pc-backup-vault/jobs.
                    # The Neon JobReportWindow cannot load those IDs and previously showed
                    # the misleading message "Backup-Job nicht gefunden".
                    if payload_target != "FILESYSTEM":
                        try:
                            report_cls = getattr(ui_module, "JobReportWindow", None)
                            if job_id and report_cls:
                                report_cls(self, job_id)
                        except Exception:
                            pass

                    try:
                        self.notify_kc(
                            "backup_success",
                            "Assistent-Backup erfolgreich",
                            f"Plan {plan_name} wurde abgeschlossen.",
                            "INFO",
                            {"job_id": str(job_id or ""), "plan": plan_name},
                        )
                    except Exception:
                        pass

                self.after(0, success)

            except BackupCancelled:
                self.after(0, lambda: finish_ui(f"Assistent-Job '{plan_name}' wurde abgebrochen."))
            except Exception as exc:
                error = str(exc)

                def failed():
                    finish_ui(f"Assistent-Job '{plan_name}' fehlgeschlagen.")
                    messagebox.showerror(
                        "PC Backup Vault",
                        f"Der Job wurde gespeichert, konnte aber nicht ausgeführt werden:\n\n{error}",
                        parent=self,
                    )

                self.after(0, failed)

        threading.Thread(target=work, daemon=True).start()

    # Applied after the earlier integration, so this corrected implementation wins.
    AppClass.run_assistant_plan_now_v180 = run_assistant_plan_now_v180
