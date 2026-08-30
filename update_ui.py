from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk

from auto_updater import download_and_verify, fetch_latest_release, launch_installer
from config_store import APP_VERSION


def enable_auto_update(app_class):
    """Attach safe GitHub-release update UX without changing backup engine behavior."""
    if getattr(app_class, "_auto_update_enabled", False):
        return app_class

    original_build = app_class._build

    def _close_for_update(self):
        try:
            self._write_start_protocol("UPDATE", "Geprüftes Update-Setup gestartet")
        except Exception:
            pass
        try:
            if getattr(self, "_status_unsubscribe", None):
                self._status_unsubscribe()
        except Exception:
            pass
        try:
            lock = getattr(self, "_instance_lock", None)
            if lock:
                lock.release()
                self._instance_lock = None
        except Exception:
            pass
        self.destroy()

    def _show_update_window(self, info):
        existing = getattr(self, "_update_window", None)
        try:
            if existing is not None and existing.winfo_exists():
                existing.deiconify(); existing.lift(); existing.focus_force(); return
        except Exception:
            pass

        win = tk.Toplevel(self)
        self._update_window = win
        win.title("PC Backup Vault – Update")
        win.geometry("560x300")
        win.resizable(False, False)
        win.transient(self)
        win.grab_set()

        body = ttk.Frame(win, padding=18)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Neue Version verfügbar", font=("Segoe UI", 15, "bold")).pack(anchor="w")
        ttk.Label(body, text=f"Installiert: {APP_VERSION}    Neu: {info.version}").pack(anchor="w", pady=(5, 12))
        ttk.Label(
            body,
            text="Das Setup wird von der offiziellen GitHub-Release-Seite geladen und vor der Installation mit SHA-256 geprüft.",
            wraplength=510,
        ).pack(anchor="w")

        progress = ttk.Progressbar(body, mode="determinate", maximum=100)
        progress.pack(fill="x", pady=(18, 5))
        status = ttk.Label(body, text="Bereit zum Update.")
        status.pack(anchor="w")
        detail = ttk.Label(body, text="", foreground="#475569")
        detail.pack(anchor="w", pady=(2, 12))

        buttons = ttk.Frame(body)
        buttons.pack(fill="x", side="bottom")
        btn_later = ttk.Button(buttons, text="Später", command=win.destroy)
        btn_later.pack(side="right")
        btn_install = ttk.Button(buttons, text="Update herunterladen und installieren")
        btn_install.pack(side="right", padx=(0, 8))

        def set_progress(done: int, total: int, text: str):
            def apply():
                if total > 0:
                    pct = min(100.0, done / total * 100.0)
                    progress.configure(mode="determinate")
                    progress["value"] = pct
                    detail.configure(text=f"{done / 1024 / 1024:.1f} MB / {total / 1024 / 1024:.1f} MB · {pct:.1f} %")
                else:
                    progress.configure(mode="indeterminate")
                    progress.start(12)
                    detail.configure(text=f"{done / 1024 / 1024:.1f} MB geladen")
                status.configure(text=text)
            self.after(0, apply)

        def start_install():
            if getattr(self, "_backup_running", False):
                messagebox.showwarning(
                    "Update zurückgestellt",
                    "Während einer laufenden Sicherung wird kein Programm-Update gestartet. Bitte die Sicherung zuerst beenden.",
                    parent=win,
                )
                return
            btn_install.configure(state="disabled")
            btn_later.configure(state="disabled")
            status.configure(text="Update wird vorbereitet…")
            progress.configure(mode="indeterminate")
            progress.start(12)

            def worker():
                try:
                    setup = download_and_verify(info, progress=set_progress)
                    def ready():
                        progress.stop()
                        progress.configure(mode="determinate")
                        progress["value"] = 100
                        status.configure(text="Download und SHA-256-Prüfung erfolgreich.")
                        detail.configure(text="Das geprüfte Setup wird jetzt gestartet.")
                        try:
                            launch_installer(setup)
                        except Exception as exc:
                            btn_install.configure(state="normal")
                            btn_later.configure(state="normal")
                            messagebox.showerror("Update", f"Setup konnte nicht gestartet werden:\n{exc}", parent=win)
                            return
                        self.after(350, self._close_for_update)
                    self.after(0, ready)
                except Exception as exc:
                    error_text = str(exc)
                    def failed(error_text=error_text):
                        progress.stop()
                        progress.configure(mode="determinate")
                        progress["value"] = 0
                        status.configure(text="Update wurde nicht installiert.")
                        detail.configure(text="Die bestehende Installation bleibt unverändert.")
                        btn_install.configure(state="normal")
                        btn_later.configure(state="normal")
                        messagebox.showerror("Update fehlgeschlagen", error_text, parent=win)
                    self.after(0, failed)

            threading.Thread(target=worker, daemon=True).start()

        btn_install.configure(command=start_install)

    def check_for_updates(self, *, manual: bool = False):
        if getattr(self, "_update_check_running", False):
            return
        self._update_check_running = True
        if manual:
            try:
                self._write_start_protocol("UPDATE_CHECK", "Manuelle Update-Prüfung")
            except Exception:
                pass

        def worker():
            info = fetch_latest_release(APP_VERSION)
            def finish():
                self._update_check_running = False
                if info:
                    self._show_update_window(info)
                elif manual:
                    messagebox.showinfo("PC Backup Vault – Update", f"Version {APP_VERSION} ist aktuell.", parent=self)
            self.after(0, finish)
        threading.Thread(target=worker, daemon=True).start()

    def wrapped_build(self):
        original_build(self)
        try:
            top = self.winfo_children()[0]
            ttk.Button(top, text="⬇ Update", command=lambda: self.check_for_updates(manual=True)).pack(side="right", padx=(0, 6))
        except Exception:
            pass

    app_class._build = wrapped_build
    app_class.check_for_updates = check_for_updates
    app_class._show_update_window = _show_update_window
    app_class._close_for_update = _close_for_update
    app_class._auto_update_enabled = True
    return app_class


def schedule_startup_update_check(app, delay_ms: int = 2500):
    """Schedule one non-blocking startup check after the main UI is ready."""
    app.after(delay_ms, lambda: app.check_for_updates(manual=False))
