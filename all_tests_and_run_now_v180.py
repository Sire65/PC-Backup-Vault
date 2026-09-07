from __future__ import annotations

import threading
import tkinter as tk
from datetime import datetime
from tkinter import ttk, messagebox, filedialog

from backup_engine import BackupCancelled, guard_active
from object_store import make_b2_store
from plan_runner import run_plan
from scheduler import task_status
from vault_db import test_connection
from kc_communication import make_client as make_kc_client


def apply_all_tests_and_run_now_v180(AppClass, AssistantClass, ui_module):
    """Add a consolidated test run and make assistant jobs optionally run immediately.

    The consolidated run contains the complete TÜV test set plus the live tests which are
    otherwise reached by clicking the status LEDs. Existing individual results and TÜV
    persistence remain intact.
    """

    # ------------------------------------------------------------------
    # 1) System bar: one button runs the complete TÜV plus the live LED
    #    checks and shows one consolidated evaluation.
    # ------------------------------------------------------------------
    original_build = AppClass._build

    def _build(self):
        original_build(self)
        sysbar = None
        for child in self.winfo_children():
            if not isinstance(child, tk.Frame):
                continue
            for sub in child.winfo_children():
                try:
                    if isinstance(sub, tk.Label) and str(sub.cget("text")) == "Systemstatus":
                        sysbar = child
                        break
                except Exception:
                    pass
            if sysbar is not None:
                break
        if sysbar is not None:
            self.btn_all_tests_v180 = ttk.Button(
                sysbar,
                text="✓ Alle Tests durchführen",
                command=self.run_all_tests_v180,
            )
            self.btn_all_tests_v180.pack(side="left", padx=(2, 10))

    AppClass._build = _build

    def run_all_tests_v180(self):
        if guard_active(self.store.data):
            messagebox.showwarning(
                "Weihnachtsmarkt-Schutz",
                "04.–13.12. wird kein Online-Gesamttest gegen Neon ausgeführt.",
                parent=self,
            )
            return
        profile = self.active_profile()
        dsn = self.active_dsn()
        if not profile or not dsn:
            messagebox.showwarning(
                "PC Backup Vault",
                "Bitte zuerst den Datenbankzugang einrichten.",
                parent=self,
            )
            return

        win = tk.Toplevel(self)
        win.title("PC Backup Vault – Alle Tests")
        win.geometry("1120x730")
        win.minsize(920, 580)
        win.transient(self)

        head = ttk.Frame(win, padding=(14, 12, 14, 8))
        head.pack(fill="x")
        ttk.Label(head, text="Alle Tests durchführen", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        lbl_summary = ttk.Label(head, text="Prüfung läuft …")
        lbl_summary.pack(anchor="w", pady=(5, 0))
        bar = ttk.Progressbar(head, mode="indeterminate")
        bar.pack(fill="x", pady=(8, 0))
        bar.start(12)

        body = ttk.Frame(win, padding=(14, 0, 14, 8))
        body.pack(fill="both", expand=True)
        tree = ttk.Treeview(body, columns=("code", "name", "result", "details"), show="headings")
        tree.heading("code", text="Prüfung")
        tree.heading("name", text="Einzeltest")
        tree.heading("result", text="Ergebnis")
        tree.heading("details", text="Details")
        tree.column("code", width=90, anchor="w")
        tree.column("name", width=250, anchor="w")
        tree.column("result", width=80, anchor="center")
        tree.column("details", width=620, anchor="w")
        sy = ttk.Scrollbar(body, orient="vertical", command=tree.yview)
        sx = ttk.Scrollbar(body, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        tree.grid(row=0, column=0, sticky="nsew")
        sy.grid(row=0, column=1, sticky="ns")
        sx.grid(row=1, column=0, sticky="ew")
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)

        footer = ttk.Frame(win, padding=(14, 4, 14, 12))
        footer.pack(fill="x")
        ttk.Label(
            footer,
            text="Enthält TÜV/Core-Prüfungen und die Live-Einzeltests der Status-LEDs. Jeder Einzeltest bleibt sichtbar und die TÜV-Prüfungen werden weiterhin im TÜV-Protokoll gespeichert.",
            wraplength=680,
        ).pack(side="left", fill="x", expand=True)

        button_box = ttk.Frame(footer)
        button_box.pack(side="right", padx=(10, 0))
        btn_copy = ttk.Button(button_box, text="📋 Tests kopieren", state="disabled")
        btn_copy.pack(side="left", padx=(0, 6))
        btn_save = ttk.Button(button_box, text="💾 Datei erstellen", state="disabled")
        btn_save.pack(side="left", padx=(0, 6))
        ttk.Button(button_box, text="Schließen", command=win.destroy).pack(side="left")

        try:
            self.btn_all_tests_v180.configure(state="disabled")
        except Exception:
            pass

        report_holder = {"text": ""}

        def make_report(checks):
            passed = sum(1 for c in checks if str(c[2]).upper() == "PASS")
            warns = sum(1 for c in checks if str(c[2]).upper() == "WARN")
            failed = sum(1 for c in checks if str(c[2]).upper() == "FAIL")
            overall = "FEHLER" if failed else ("WARNUNGEN" if warns else "PASS")
            lines = [
                "PC BACKUP VAULT – ALLE TESTS",
                "=" * 48,
                f"Erstellt: {datetime.now().astimezone().strftime('%d.%m.%Y %H:%M:%S')}",
                f"Gesamtergebnis: {overall}",
                f"Prüfungen: {len(checks)} · PASS: {passed} · Warnungen: {warns} · Fehler: {failed}",
                "",
            ]
            for code, name, result, details in checks:
                lines.append(f"{code} | {name} | {result} | {details}")
            return "\n".join(lines), overall, passed, warns, failed

        def copy_report():
            text = report_holder.get("text") or ""
            if not text:
                return
            try:
                self.clipboard_clear()
                self.clipboard_append(text)
                self.update_idletasks()
                messagebox.showinfo("PC Backup Vault", "Testergebnis wurde in die Zwischenablage kopiert.", parent=win)
            except Exception as exc:
                messagebox.showerror("PC Backup Vault", f"Kopieren fehlgeschlagen:\n\n{exc}", parent=win)

        def save_report():
            text = report_holder.get("text") or ""
            if not text:
                return
            stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            path = filedialog.asksaveasfilename(
                parent=win,
                title="Testergebnis speichern",
                defaultextension=".txt",
                initialfile=f"PC_Backup_Vault_Alle_Tests_{stamp}.txt",
                filetypes=[("Textdatei", "*.txt"), ("Alle Dateien", "*.*")],
            )
            if not path:
                return
            try:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(text)
                messagebox.showinfo("PC Backup Vault", f"Testergebnis gespeichert:\n\n{path}", parent=win)
            except Exception as exc:
                messagebox.showerror("PC Backup Vault", f"Datei konnte nicht erstellt werden:\n\n{exc}", parent=win)

        btn_copy.configure(command=copy_report)
        btn_save.configure(command=save_report)

        def work():
            checks = []
            try:
                # Complete TÜV/Core set, including professional 1.8 filesystem checks.
                checks.extend(list(ui_module.run_tuev(
                    dsn,
                    bool(self.master_key()),
                    bool(self.store.data.get("recovery_key_exported")),
                    profile,
                    self.store.data,
                ) or []))
            except Exception as exc:
                checks.append(("ALL-999", "TÜV/Core-Gesamttest", "FAIL", str(exc)))

            # Live tests equivalent to the tests behind the clickable status LEDs.
            try:
                ok, msg = test_connection(dsn)
                checks.append(("LED-NEON", "Neon Live-Verbindung", "PASS" if ok else "FAIL", msg))
            except Exception as exc:
                checks.append(("LED-NEON", "Neon Live-Verbindung", "FAIL", str(exc)))

            try:
                b2cfg = self.store.get_b2_runtime_config()
                if not b2cfg.get("configured"):
                    checks.append(("LED-B2", "B2 Live-Verbindung", "WARN", "B2 nicht vollständig eingerichtet"))
                else:
                    b2store = make_b2_store(b2cfg)
                    ok, msg = b2store.ping() if b2store else (False, "B2 nicht eingerichtet")
                    checks.append(("LED-B2", "B2 Live-Verbindung", "PASS" if ok else "FAIL", msg))
            except Exception as exc:
                checks.append(("LED-B2", "B2 Live-Verbindung", "FAIL", str(exc)))

            try:
                has_key = bool(self.master_key())
                checks.append(("LED-VAULT", "Lokaler Tresor", "PASS" if has_key else "FAIL", "Tresorschlüssel vorhanden" if has_key else "Tresorschlüssel fehlt"))
            except Exception as exc:
                checks.append(("LED-VAULT", "Lokaler Tresor", "FAIL", str(exc)))

            try:
                plans = list(self.store.data.get("plans", []) or [])
                if not plans:
                    checks.append(("LED-SCHED", "Windows Scheduler", "WARN", "Noch kein Backup-Plan vorhanden"))
                else:
                    ok, msg = task_status(plans[0])
                    detail = "Windows-Aufgabe vorhanden" if ok else ((msg or "Aufgabe nicht gefunden").splitlines()[0])
                    checks.append(("LED-SCHED", "Windows Scheduler", "PASS" if ok else "WARN", detail))
            except Exception as exc:
                checks.append(("LED-SCHED", "Windows Scheduler", "WARN", str(exc)))

            try:
                kc_cfg = self.store.data.get("kc_communication") or {}
                if not kc_cfg.get("enabled"):
                    checks.append(("LED-KC", "KC Kommunikation Live", "WARN", "KC Kommunikation ist ausgeschaltet"))
                else:
                    client = make_kc_client(self.store)
                    if not client:
                        checks.append(("LED-KC", "KC Kommunikation Live", "WARN", "Gerät noch nicht registriert / gekoppelt"))
                    else:
                        ok, msg = client.test()
                        level = "PASS" if ok else ("WARN" if "pending" in str(msg).lower() or "pairing" in str(msg).lower() else "FAIL")
                        checks.append(("LED-KC", "KC Kommunikation Live", level, msg))
            except Exception as exc:
                checks.append(("LED-KC", "KC Kommunikation Live", "FAIL", str(exc)))

            def done():
                # Always re-enable the main button even if the result window was closed.
                try:
                    self.btn_all_tests_v180.configure(state="normal")
                except Exception:
                    pass
                try:
                    self.refresh_system_status()
                except Exception:
                    pass
                if not win.winfo_exists():
                    return
                bar.stop()
                bar.configure(mode="determinate", maximum=100, value=100)
                report, overall, passed, warns, failed = make_report(checks)
                report_holder["text"] = report
                lbl_summary.configure(
                    text=f"Gesamtergebnis: {overall} · Prüfungen: {len(checks)} · PASS: {passed} · Warnungen: {warns} · Fehler: {failed}"
                )
                for c in checks:
                    tree.insert("", "end", values=c)
                btn_copy.configure(state="normal")
                btn_save.configure(state="normal")

            self.after(0, done)

        threading.Thread(target=work, daemon=True).start()

    AppClass.run_all_tests_v180 = run_all_tests_v180

    # ------------------------------------------------------------------
    # 2) Assistant: default is "run immediately". The existing plan is
    #    still saved first, then the same run_plan path is used with the
    #    existing live progress/report UI.
    # ------------------------------------------------------------------
    original_options = AssistantClass.step_options

    def step_options(self):
        original_options(self)
        self.data.setdefault("run_now", True)
        run_now = tk.BooleanVar(value=bool(self.data.get("run_now", True)))
        ttk.Separator(self.body, orient="horizontal").pack(fill="x", pady=(12, 8))
        ttk.Checkbutton(
            self.body,
            text="Job nach dem Speichern sofort ausführen",
            variable=run_now,
            command=lambda: self.data.update(run_now=run_now.get()),
        ).pack(anchor="w", pady=4)
        ttk.Label(
            self.body,
            text="Standard: EIN. Der Job wird zuerst gespeichert und anschließend sofort gestartet.",
            wraplength=790,
        ).pack(anchor="w", padx=(22, 0))

    AssistantClass.step_options = step_options

    original_summary = AssistantClass.step_summary

    def step_summary(self):
        original_summary(self)
        state = "Ja" if self.data.get("run_now", True) else "Nein"
        ttk.Label(
            self.body,
            text=f"Sofort ausführen: {state}",
            font=("Segoe UI", 9, "bold"),
        ).pack(anchor="w", pady=(10, 0))
        if self.data.get("run_now", True):
            self.btn_next.configure(text="✓ Speichern & jetzt ausführen")

    AssistantClass.step_summary = step_summary

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

        try:
            self._reset_live_progress()
            control = self._begin_backup_control()
        except Exception as exc:
            messagebox.showerror("PC Backup Vault", str(exc), parent=self)
            return

        self.lbl_progress.configure(text=f"Assistent-Job '{plan_name}' startet …")

        def cb(done, total, msg, metrics=None):
            self.after(0, lambda: self._progress(done, total, msg, metrics))

        def work():
            try:
                result = run_plan(plan_id, cb, control=control)
                job_id = result.get("job_id") if isinstance(result, dict) else None

                def success():
                    self.lbl_progress.configure(text=f"Assistent-Job '{plan_name}' abgeschlossen.")
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
                    try:
                        self.refresh_status()
                        self.refresh_system_status()
                    except Exception:
                        pass
                    try:
                        self._finish_backup_control()
                    except Exception:
                        pass

                self.after(0, success)
            except BackupCancelled:
                self.after(0, lambda: self.lbl_progress.configure(text=f"Assistent-Job '{plan_name}' abgebrochen."))
                try:
                    self.after(0, self._finish_backup_control)
                except Exception:
                    pass
            except Exception as exc:
                error_text = str(exc)

                def failed(error=error_text):
                    try:
                        self._finish_backup_control()
                    except Exception:
                        pass
                    messagebox.showerror(
                        "PC Backup Vault",
                        f"Der Job wurde gespeichert, konnte aber nicht ausgeführt werden:\n\n{error}",
                        parent=self,
                    )
                self.after(0, failed)

        threading.Thread(target=work, daemon=True).start()

    AppClass.run_assistant_plan_now_v180 = run_assistant_plan_now_v180

    original_finish = AssistantClass.finish

    def finish(self):
        before = {p.get("id") for p in self.store.data.get("plans", [])}
        run_now = bool(self.data.get("run_now", True))
        plan_name = self.data.get("name") or "Mein Backup"
        original_finish(self)
        after = [p for p in self.store.data.get("plans", []) if p.get("id") not in before]
        if run_now and after:
            new_plan = after[-1]
            self.app.after(
                150,
                lambda pid=new_plan.get("id"), name=plan_name: self.app.run_assistant_plan_now_v180(pid, name),
            )

    AssistantClass.finish = finish
