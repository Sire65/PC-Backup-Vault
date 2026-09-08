from __future__ import annotations

import os
import tempfile
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox

from unified_reporting_v193 import (
    human_size,
    latest_local_job_report,
    load_local_job_report,
    persist_local_job_report,
    report_text as unified_report_text,
    save_report_csv as save_unified_csv,
    save_report_txt as save_unified_txt,
)


def _parse_dt(value):
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def apply_unified_reporting_v193(AppClass, storage_module, hidrive_integration_module, ui_module=None):
    """Consolidate filesystem/NAS/HiDrive job identity and all user-facing reports.

    Existing backup, crypto, SFTP, lifecycle and restore engines remain untouched.
    """
    if getattr(AppClass, "_unified_reporting_v193", False):
        return

    original_fs = storage_module.filesystem_backup

    def filesystem_backup(app, paths, target, control=None, progress=None, plan_name=None):
        path_list = list(paths or [])
        result = original_fs(app, path_list, target, control=control, progress=progress, plan_name=plan_name)
        if not result.get("source_to_target"):
            enriched = persist_local_job_report(app.store, result, path_list, target)
            result.clear(); result.update(enriched)
        return result

    storage_module.filesystem_backup = filesystem_backup

    # hidrive_integration_v192 imported the SFTP function into its module namespace.
    # Patching that one reference reaches manual and One-Touch HiDrive jobs without
    # altering the proven SFTP transport implementation itself.
    original_sftp = hidrive_integration_module.filesystem_backup_sftp

    def filesystem_backup_sftp(app, paths, target, control=None, progress=None, plan_name=None):
        path_list = list(paths or [])
        result = original_sftp(app, path_list, target, control=control, progress=progress, plan_name=plan_name)
        if not result.get("source_to_target"):
            enriched = persist_local_job_report(app.store, result, path_list, target)
            result.clear(); result.update(enriched)
        return result

    hidrive_integration_module.filesystem_backup_sftp = filesystem_backup_sftp

    # KC Kommunikation receives the same job facts as the local report. This fills
    # the previously blank size/duration/speed fields and keeps source/target tied
    # to the exact job ID. Only credential-free audit fields are added.
    original_notify = AppClass.notify_kc

    def notify_kc(self, event, title, message, severity="INFO", details=None):
        payload = dict(details or {})
        job_id = str(payload.get("job_id") or "").strip()
        if job_id:
            local = load_local_job_report(self.store, job_id)
            if local:
                files = int(local.get("files") or local.get("file_count") or 0)
                original_bytes = int(local.get("original_bytes") or 0)
                duration = float(local.get("duration_seconds") or 0)
                speed = int(local.get("avg_speed_bps") or 0)
                payload.update({
                    "job_id": job_id,
                    "files": files,
                    "file_count": files,
                    "directories": int(local.get("directory_count") or 0),
                    "directory_count": int(local.get("directory_count") or 0),
                    "bytes": original_bytes,
                    "original_bytes": original_bytes,
                    "stored_bytes": int(local.get("stored_bytes") or 0),
                    "duration": duration,
                    "duration_seconds": duration,
                    "avg_speed_bps": speed,
                    "target": local.get("target_label") or "–",
                    "storage_target": local.get("target_label") or "–",
                    "source": local.get("source_label") or "–",
                    "source_to_target": local.get("source_to_target") or "–",
                    "transport": local.get("transport_label") or "–",
                    "storage_backend": local.get("backend_label") or "–",
                    "verification": (local.get("verification") or {}).get("status", "noch nicht durchgeführt"),
                })
        return original_notify(self, event, title, message, severity, payload)

    AppClass.notify_kc = notify_kc

    if ui_module is not None and hasattr(ui_module, "JobReportWindow"):
        ReportWindow = ui_module.JobReportWindow
        original_load = ReportWindow.load
        original_copy = ReportWindow.copy_report
        original_print = ReportWindow.print_report
        original_send = ReportWindow.send_report_to_kc
        original_save_txt = ReportWindow.save_txt
        original_save_csv = ReportWindow.save_csv

        def _local(self):
            return bool(getattr(self, "_unified_local_v193", False))

        def load(self):
            local = load_local_job_report(self.app.store, self.job_id)
            if not local:
                self._unified_local_v193 = False
                return original_load(self)
            self._unified_local_v193 = True
            self.report = local
            status = str(local.get("status") or "–").upper()
            self.status_lbl.config(text="GRÜN" if status == "SUCCESS" else status)
            files = int(local.get("files") or local.get("file_count") or 0)
            self.summary_lbl.config(
                text=f"{files} Dateien · {human_size(local.get('original_bytes'))} · "
                     f"{float(local.get('duration_seconds') or 0):.1f} s · Ø {human_size(local.get('avg_speed_bps'))}/s · "
                     f"Ziel: {local.get('target_label') or '–'}"
            )
            self.text.config(state="normal")
            self.text.delete("1.0", "end")
            self.text.insert("1.0", unified_report_text(local))
            self.text.config(state="disabled")

        def copy_report(self):
            if not _local(self):
                return original_copy(self)
            text = unified_report_text(self.report)
            self.clipboard_clear(); self.clipboard_append(text); self.update()
            messagebox.showinfo("PC Backup Vault", "Report wurde in die Zwischenablage kopiert.", parent=self)

        def print_report(self):
            if not _local(self):
                return original_print(self)
            try:
                fd, path = tempfile.mkstemp(prefix="PC_Backup_Vault_Report_", suffix=".txt")
                os.close(fd)
                Path(path).write_text(unified_report_text(self.report), encoding="utf-8")
                os.startfile(path, "print")
                messagebox.showinfo("PC Backup Vault", "Report wurde an den Windows-Druckdialog übergeben.", parent=self)
            except Exception as exc:
                messagebox.showerror("PC Backup Vault", f"Drucken nicht möglich:\n{exc}", parent=self)

        def save_txt(self):
            if not _local(self):
                return original_save_txt(self)
            path = filedialog.asksaveasfilename(parent=self, title="Backup-Report als TXT speichern", defaultextension=".txt", filetypes=[("Text", "*.txt")], initialfile=f"Backup_Report_{self.job_id}.txt")
            if path:
                save_unified_txt(self.report, path)
                messagebox.showinfo("PC Backup Vault", "Report gespeichert.", parent=self)

        def save_csv(self):
            if not _local(self):
                return original_save_csv(self)
            path = filedialog.asksaveasfilename(parent=self, title="Backup-Report als CSV speichern", defaultextension=".csv", filetypes=[("CSV", "*.csv")], initialfile=f"Backup_Report_{self.job_id}.csv")
            if path:
                save_unified_csv(self.report, path)
                messagebox.showinfo("PC Backup Vault", "CSV gespeichert.", parent=self)

        def send_report_to_kc(self):
            if not _local(self):
                return original_send(self)
            r = self.report
            status = str(r.get("status") or "UNKNOWN").upper()
            severity = "ERROR" if status in ("FAIL", "ERROR", "FAILED") else "INFO"
            self.app.notify_kc(
                "backup_failed" if severity == "ERROR" else "backup_success",
                f"Backup-Report: {status}",
                f"Job {self.job_id} · {r.get('source_to_target') or '–'} · {human_size(r.get('original_bytes'))}",
                severity,
                {"job_id": self.job_id},
            )
            messagebox.showinfo("PC Backup Vault", "Report wurde zur Übergabe an KC Kommunikation eingestellt.", parent=self)

        ReportWindow.load = load
        ReportWindow.copy_report = copy_report
        ReportWindow.print_report = print_report
        ReportWindow.save_txt = save_txt
        ReportWindow.save_csv = save_csv
        ReportWindow.send_report_to_kc = send_report_to_kc

        original_last_report = AppClass.open_last_report

        def open_last_report(self):
            local = latest_local_job_report(self.store)
            local_dt = _parse_dt((local or {}).get("reported_at"))
            neon_rows = []
            dsn = self.active_dsn()
            if dsn:
                try:
                    neon_rows = ui_module.recent_jobs(dsn, 1)
                except Exception:
                    neon_rows = []
            neon_dt = None
            if neon_rows:
                neon_dt = neon_rows[0][2] or neon_rows[0][1]
            if local and local_dt and (not neon_dt or local_dt >= neon_dt):
                return ui_module.JobReportWindow(self, str(local.get("job_id")))
            return original_last_report(self)

        AppClass.open_last_report = open_last_report

    AppClass._unified_reporting_v193 = True
