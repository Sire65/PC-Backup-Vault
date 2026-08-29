from __future__ import annotations

import threading
from pathlib import Path
from tkinter import messagebox, ttk

from backup_engine import backup_files, BackupCancelled, ChristmasGuard, LimitBlocked, collect_paths
from config_store import APP_VERSION
from interrupted_recovery import clear_checkpoint, save_manual_checkpoint, update_job_id
from kc_backup_engine_adapter import execute_prepared_backup, prepare_one_touch_backup
from kc_backup_job_store import load_jobs, save_jobs
from kc_backup_program_registry import default_registry
from kc_backup_program_store import load_program_registry
from kc_backup_programs_ui import KCProgramsWindow
from kc_backup_scheduler_ui import BackupSchedulerWindow
from verification import verify_job


class PersistentBackupSchedulerWindow(BackupSchedulerWindow):
    """Calendar window whose job mutations are written atomically to disk."""

    def __init__(self, master, *, store_path: str | Path, program_id: str = "pc-backup-vault", on_one_touch=None):
        self.store_path = Path(store_path)
        store_existed = self.store_path.exists()
        try:
            jobs = load_jobs(self.store_path)
        except Exception as exc:
            jobs = []
            messagebox.showwarning(
                "Backup-Kalender",
                f"Gespeicherte Scheduler-Jobs konnten nicht gelesen werden.\n\n{exc}\n\n"
                "Es wird mit einer sicheren leeren Ansicht geöffnet; die beschädigte Datei wird nicht automatisch überschrieben.",
                parent=master,
            )
            self._store_read_failed = True
        else:
            self._store_read_failed = False
        force_empty = bool(store_existed and not jobs)
        super().__init__(master, program_id=program_id, jobs=jobs, on_one_touch=on_one_touch)
        if force_empty:
            self.model.jobs = []
            self.refresh()

    def _persist(self):
        if getattr(self, "_store_read_failed", False):
            raise RuntimeError("Scheduler-Datei wurde beim Öffnen als fehlerhaft erkannt; automatisches Überschreiben ist gesperrt.")
        save_jobs(self.store_path, self.model.jobs)

    def _save_job(self, job):
        self.model.add(job)
        try:
            self._persist()
        except Exception as exc:
            self.model.remove(job.job_id)
            messagebox.showerror("Backup-Kalender", f"Job konnte nicht sicher gespeichert werden:\n{exc}", parent=self)
        self.refresh()

    def _toggle_selected(self):
        job_id = self._selected_job_id()
        if not job_id:
            return
        job = next(job for job in self.model.jobs if job.job_id == job_id)
        previous = bool(job.enabled)
        self.model.set_enabled(job_id, not previous)
        try:
            self._persist()
        except Exception as exc:
            self.model.set_enabled(job_id, previous)
            messagebox.showerror("Backup-Kalender", f"Änderung konnte nicht sicher gespeichert werden:\n{exc}", parent=self)
        self.refresh()

    def _remove_selected(self):
        job_id = self._selected_job_id()
        if not job_id:
            return
        previous = list(self.model.jobs)
        self.model.remove(job_id)
        try:
            self._persist()
        except Exception as exc:
            self.model.jobs = previous
            messagebox.showerror("Backup-Kalender", f"Job konnte nicht sicher entfernt werden:\n{exc}", parent=self)
        self.refresh()


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


def enable_backup_central(App):
    """Attach Backup Central to the existing UI without replacing the backup engine."""
    if getattr(App, "_kc_backup_central_enabled", False):
        return

    original_build = App._build

    def open_backup_calendar(self):
        path = self.store.path.parent / "KC_BACKUP_SCHEDULER_JOBS.json"
        return PersistentBackupSchedulerWindow(
            self,
            store_path=path,
            program_id="pc-backup-vault",
            on_one_touch=lambda _plan: self.run_default_one_touch(),
        )

    def open_kc_programs(self):
        path = self.store.path.parent / "KC_BACKUP_PROGRAMS.json"
        try:
            registry = load_program_registry(path, default_registry())
        except Exception as exc:
            messagebox.showerror(
                "KC Programme",
                f"Die gespeicherte Programmkonfiguration konnte nicht sicher gelesen werden.\n\n{exc}\n\n"
                "Es wurde nichts verändert oder gestartet.",
                parent=self,
            )
            return None

        def start_program_backup(program, scope):
            if getattr(self, "_backup_running", False):
                messagebox.showwarning("KC Programme", "Es läuft bereits eine Sicherung.", parent=self)
                return
            self.selected = collect_paths([str(path) for path in scope.paths])
            self._refresh_tree()
            self.update_backup_recommendation()
            self._update_backup_button_state()
            self.run_default_one_touch(program_id=program.program_id)

        return KCProgramsWindow(
            self,
            registry=registry,
            store_path=path,
            on_backup=start_program_backup,
        )

    def secure_one_touch(self, program_id="pc-backup-vault"):
        if getattr(self, "_backup_running", False):
            return
        if not self.selected:
            messagebox.showwarning(
                "One-Touch",
                "Bitte zuerst Dateien oder einen Ordner auswählen.\n\nDanach reicht ein Klick auf One-Touch.",
                parent=self,
            )
            return
        profile = self.active_profile()
        dsn = self.active_dsn()
        key = self.master_key()
        if not profile or not dsn or not key:
            messagebox.showwarning("One-Touch", "Datenbankzugang oder lokaler Tresorschlüssel fehlt.", parent=self)
            return

        payload = self._selected_payload_code()
        effective = self._effective_payload_code()
        b2_cfg = self.store.get_b2_runtime_config()
        target_ready = bool(dsn) and effective != "B2_MISSING" and (effective != "B2" or bool(b2_cfg.get("configured")))
        recovery_ready = bool(key) and bool(self.store.data.get("recovery_key_exported"))
        prepared = prepare_one_touch_backup(
            program_id=program_id,
            paths=self.selected,
            target_ready=target_ready,
            recovery_material_ready=recovery_ready,
            backup_mode=self._selected_mode_code(),
            payload_target=payload,
        )
        if not prepared.allowed:
            messagebox.showwarning(
                "One-Touch – Probelauf blockiert",
                "Es wurde nichts gesichert.\n\n" + "\n".join(f"• {item}" for item in prepared.blockers),
                parent=self,
            )
            return

        paths = list(prepared.paths)
        total_bytes = sum((p.stat().st_size for p in paths if p.exists()), 0)
        save_manual_checkpoint(key, paths, prepared.backup_mode, prepared.payload_target, None)
        self._reset_live_progress(len(paths), total_bytes)
        control = self._begin_backup_control()
        self.lbl_progress.config(text=f"One-Touch {program_id}: Probelauf OK – sichere Sicherung startet …")

        def cb(done, total, message, metrics=None):
            self.after(0, lambda: self._progress(done, total, message, metrics))

        def recovery_hook(event, payload_):
            if event == "job_created":
                update_job_id(key, payload_.get("job_id", ""))

        def work():
            try:
                result = execute_prepared_backup(
                    prepared,
                    engine=backup_files,
                    dsn=dsn,
                    key_b64=key,
                    profile=profile,
                    config=self.store.data,
                    object_store_config=b2_cfg,
                    progress=cb,
                    control=control,
                    recovery_hook=recovery_hook,
                )
                job_id = result.get("job_id")
                verification = verify_job(
                    dsn,
                    key,
                    job_id,
                    mode="FULL",
                    object_store_config=b2_cfg,
                    progress=cb,
                    control=control,
                    app_version=APP_VERSION,
                )
                clear_checkpoint()
                if getattr(verification, "result", "") != "PASS":
                    raise RuntimeError("Vollsicherung erstellt, aber die verpflichtende FULL-Verifizierung war nicht PASS. Bitte Report prüfen.")
                self.after(0, lambda: self.lbl_progress.config(text=f"One-Touch {program_id} abgeschlossen: Sicherung + FULL-Verify erfolgreich."))
                try:
                    from ui import JobReportWindow
                    self.after(0, lambda j=job_id: JobReportWindow(self, j))
                except Exception:
                    pass
                self.notify_kc(
                    "backup_success",
                    "One-Touch Backup erfolgreich",
                    f"{program_id}: Backup-Job {job_id} wurde vollständig gesichert und verifiziert.",
                    "INFO",
                    {"job_id": str(job_id or ""), "program_id": program_id, "verify": "FULL"},
                )
                self.after(0, self.refresh_status)
                self.after(0, self.refresh_system_status)
            except BackupCancelled:
                clear_checkpoint()
                self.after(0, lambda: self.lbl_progress.config(text="One-Touch abgebrochen – unvollständiger Lauf bereinigt."))
                self.after(0, lambda: messagebox.showinfo("One-Touch", "One-Touch wurde sicher abgebrochen.", parent=self))
            except (LimitBlocked, ChristmasGuard) as exc:
                clear_checkpoint()
                msg = str(exc)
                self.after(0, lambda m=msg: messagebox.showwarning("One-Touch – Sicherheitssperre", m, parent=self))
            except Exception as exc:
                clear_checkpoint()
                msg = str(exc)
                self.notify_kc("backup_failed", "One-Touch Backup fehlgeschlagen", msg, "ERROR", {"program_id": program_id})
                self.after(0, lambda m=msg: messagebox.showerror("One-Touch", f"One-Touch fehlgeschlagen:\n{m}", parent=self))
            finally:
                self.after(0, lambda: self._set_backup_running(False))

        threading.Thread(target=work, daemon=True).start()

    def build_with_backup_central(self):
        original_build(self)
        status_button = _find_button_by_text(self, "↻ Status")
        if status_button is not None:
            program_button = ttk.Button(status_button.master, text="KC Programme", command=self.open_kc_programs)
            program_button.pack(side="right", padx=(0, 8))
            self.btn_kc_programs = program_button
            calendar_button = ttk.Button(status_button.master, text="🗓 Backup-Kalender", command=self.open_backup_calendar)
            calendar_button.pack(side="right", padx=(0, 8))
            self.btn_backup_calendar = calendar_button

    App.open_backup_calendar = open_backup_calendar
    App.open_kc_programs = open_kc_programs
    App.run_default_one_touch = secure_one_touch
    App._build = build_with_backup_central
    App._kc_backup_central_enabled = True
