from __future__ import annotations

import os
import queue
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from backup_engine import guard_active
from kc_communication import make_client as make_kc_client
from object_store import make_b2_store
from scheduler import task_status
from vault_db import initialize_schema, recent_tuev_checks, recent_verifications, test_connection


SUCCESS_STATES = {"sent", "success", "ok", "delivered", "accepted", "displayed", "opened"}
FAIL_STATES = {"failed", "error", "rejected", "dead", "dead_letter"}


def timed_percent(elapsed: float, budget: float, ceiling: int = 95) -> int:
    """Progress for tests without a measurable byte/item total.

    The bar deliberately stops below 100 % until the operation has really
    finished. This prevents a time-based indicator from claiming completion.
    """
    budget = max(0.5, float(budget or 1.0))
    return max(0, min(int(ceiling), int((max(0.0, float(elapsed)) / budget) * ceiling)))


def run_with_deadline(callable_, timeout_seconds: float):
    """Run one diagnostic behind a hard UI deadline.

    Network libraries can occasionally remain blocked below their documented
    socket timeout (DNS/TLS/provider edge cases). The inner worker is daemonized
    so the caller can regain control after the deadline. Late results are
    intentionally ignored by the UI.
    """
    result_queue: queue.Queue = queue.Queue(maxsize=1)

    def work():
        try:
            result_queue.put((True, callable_(), None), block=False)
        except Exception as exc:  # pragma: no cover - exact provider exception varies
            try:
                result_queue.put((True, None, exc), block=False)
            except Exception:
                pass

    threading.Thread(target=work, name="pbv-test-deadline-v1919", daemon=True).start()
    try:
        return result_queue.get(timeout=max(0.5, float(timeout_seconds or 1.0)))
    except queue.Empty:
        return False, None, TimeoutError(f"Test nach {int(timeout_seconds)} Sekunden beendet (Zeitüberschreitung).")


def delivery_summary_v1919(data: dict | None) -> tuple[bool, bool, str]:
    """Interpret current and legacy KC Communication router result shapes.

    In particular, current router responses can report successfully selected
    providers through `selectedChannels` instead of a singular `channel` field.
    Older PC Backup Vault versions overlooked that shape and could therefore
    label an actually delivered Push as an error.
    """
    data = data if isinstance(data, dict) else {}
    channel_states: dict[str, str] = {}
    channel_providers: dict[str, str] = {}
    notes: list[str] = []

    def mark(channel: str, state: str | None, provider=None):
        ch = str(channel or "").lower()
        if ch not in ("push", "email"):
            return
        if provider:
            channel_providers[ch] = str(provider)[:80]
        if state == "ok":
            channel_states[ch] = "ok"
        elif state == "error" and channel_states.get(ch) != "ok":
            channel_states[ch] = "error"

    def walk(obj):
        if isinstance(obj, dict):
            provider = obj.get("provider") or obj.get("providerKey") or obj.get("provider_id")
            status = str(obj.get("status") or obj.get("delivery") or "").lower()
            partial = bool(obj.get("partial"))
            ok_flag = obj.get("ok")
            successful = ok_flag is True or partial or status in SUCCESS_STATES
            failed = (ok_flag is False and not successful) or status in FAIL_STATES
            state = "ok" if successful else ("error" if failed else None)

            singular = obj.get("channel") or obj.get("selectedChannel") or obj.get("type")
            if isinstance(singular, str):
                mark(singular, state, provider)

            for field in ("selectedChannels", "channels"):
                values = obj.get(field)
                if isinstance(values, (list, tuple)):
                    for ch in values:
                        if isinstance(ch, str):
                            # `channels` can also be the requested set. Only use
                            # it as proof when the surrounding result is successful.
                            mark(ch, state if state is not None else ("ok" if field == "selectedChannels" else None), provider)

            if failed:
                err = obj.get("error") or obj.get("detail") or obj.get("message") or obj.get("error_detail")
                if err:
                    notes.append(str(err)[:220])

            for key, value in obj.items():
                if str(key).lower() in {"token", "authorization", "apikey", "password", "secret"}:
                    continue
                walk(value)
        elif isinstance(obj, list):
            for value in obj:
                walk(value)

    walk(data.get("results") if isinstance(data.get("results"), list) else data)

    sent = int(data.get("sent") or 0)
    failed_count = int(data.get("failed") or 0)
    partial_flag = bool(data.get("partial"))
    any_success = bool(data.get("ok") is True or sent > 0 or partial_flag or any(v == "ok" for v in channel_states.values()))
    any_failure = bool(failed_count > 0 or any(v == "error" for v in channel_states.values()) or (data.get("ok") is False and not any_success))

    parts: list[str] = []
    for ch, label in (("push", "Push"), ("email", "E-Mail")):
        if ch in channel_states:
            suffix = f" ({channel_providers[ch]})" if channel_providers.get(ch) else ""
            parts.append(f"{label}: {'OK' if channel_states[ch] == 'ok' else 'FEHLER'}{suffix}")
    if not parts and any_success:
        parts.append("Versand vom Server bestätigt")
    if notes:
        parts.extend(notes[:3])
    if not parts:
        text = data.get("message") or data.get("error") or "Keine Kanaldetails vom Server"
        parts.append(str(text)[:350])
    return any_success, any_failure, " · ".join(parts)


def _result_from_deadline(done, value, error, timeout_text="Test-Zeitüberschreitung"):
    if not done:
        return False, str(error or timeout_text)
    if error is not None:
        return False, str(error)
    if isinstance(value, tuple) and len(value) >= 2:
        return bool(value[0]), str(value[1])
    return True, str(value or "OK")


def apply_test_runtime_fix_v1919(AppClass, SettingsWindowClass, ui_module, kc_module):
    if getattr(AppClass, "_test_runtime_fix_v1919", False):
        return
    AppClass._test_runtime_fix_v1919 = True

    # Current KC router response compatibility.
    kc_module._delivery_summary = delivery_summary_v1919

    # ------------------------------------------------------------------
    # Settings: use the already existing inline activity row, but make it
    # determinate with percentage + elapsed time. Network tests also receive a
    # hard deadline so buttons are never left disabled forever.
    # ------------------------------------------------------------------
    original_settings_init = SettingsWindowClass.__init__

    def settings_init(self, *args, **kwargs):
        original_settings_init(self, *args, **kwargs)
        try:
            self.activity_progress.stop()
            self.activity_progress.configure(mode="determinate", maximum=100, value=0)
            self.activity_percent_v1919 = ttk.Label(self.activity_frame, text="0 %", width=6, anchor="e")
            self.activity_percent_v1919.pack(side="right", padx=(8, 0))
        except Exception:
            pass

    def activity_budget(label: str) -> int:
        text = str(label or "").lower()
        if "schema" in text or "core" in text:
            return 30
        if "b2" in text:
            return 20
        return 15

    def activity_start(self, label, buttons=()):
        if getattr(self, "_activity_started", None) is not None:
            return False
        self._activity_started = time.monotonic()
        self._activity_budget_v1919 = activity_budget(label)
        self.activity_label.config(text=label)
        self.activity_time.config(text="Laufzeit: 00:00")
        self.activity_progress.stop()
        self.activity_progress.configure(mode="determinate", maximum=100, value=0)
        try:
            self.activity_percent_v1919.config(text="0 %")
        except Exception:
            pass
        self._activity_buttons = [b for b in buttons if b is not None]
        for button in self._activity_buttons:
            try:
                button.config(state="disabled")
            except Exception:
                pass
        self._activity_tick()
        return True

    def activity_tick(self):
        started = getattr(self, "_activity_started", None)
        if started is None:
            return
        elapsed = max(0.0, time.monotonic() - started)
        pct = timed_percent(elapsed, getattr(self, "_activity_budget_v1919", 15))
        try:
            self.activity_progress["value"] = pct
            self.activity_percent_v1919.config(text=f"{pct} %")
            self.activity_time.config(text=f"Laufzeit: {int(elapsed // 60):02d}:{int(elapsed % 60):02d}")
        except Exception:
            return
        self._activity_timer = self.after(200, self._activity_tick)

    def activity_stop(self, label="Bereit."):
        if getattr(self, "_activity_timer", None) is not None:
            try:
                self.after_cancel(self._activity_timer)
            except Exception:
                pass
        self._activity_timer = None
        started = getattr(self, "_activity_started", None)
        elapsed = max(0.0, time.monotonic() - started) if started is not None else 0.0
        try:
            self.activity_progress.stop()
            self.activity_progress.configure(mode="determinate", maximum=100, value=100)
            self.activity_percent_v1919.config(text="100 %")
            self.activity_label.config(text=label)
            self.activity_time.config(text=f"Dauer: {int(elapsed // 60):02d}:{int(elapsed % 60):02d}")
        except Exception:
            pass
        self._activity_started = None
        for button in getattr(self, "_activity_buttons", []):
            try:
                button.config(state="normal")
            except Exception:
                pass
        self._activity_buttons = []

    SettingsWindowClass.__init__ = settings_init
    SettingsWindowClass._activity_start = activity_start
    SettingsWindowClass._activity_tick = activity_tick
    SettingsWindowClass._activity_stop = activity_stop

    def settings_test_profile(self):
        if guard_active(self.store.data):
            messagebox.showwarning("Weihnachtsmarkt-Schutz", "04.–13.12. sind Verbindungstests zum Backup-Ziel gesperrt.", parent=self); return
        profile = self.selected_profile()
        if not profile:
            return
        valid = self._validate_profile(profile)
        if not valid:
            return
        dsn = valid[0]
        if not self._activity_start("Datenbank-Verbindung wird geprüft …", (getattr(self, "btn_db_test", None),)):
            return

        def worker():
            done, value, error = run_with_deadline(lambda: test_connection(dsn), 15)
            ok, msg = _result_from_deadline(done, value, error)
            self.after(0, lambda: self._finish_profile_test(ok, msg))
        threading.Thread(target=worker, daemon=True).start()

    def settings_test_b2(self):
        cfg = self._b2_form_config()
        if not cfg:
            return
        if not cfg.get("configured"):
            messagebox.showwarning("PC Backup Vault", "B2 ist deaktiviert oder unvollständig.", parent=self); return
        if not self._activity_start("Backblaze B2 wird geprüft (Liste/Schreiben/Lesen/Löschen) …", (getattr(self, "btn_b2_test", None),)):
            return

        def call():
            store = make_b2_store(cfg)
            return store.test() if store else (False, "B2 nicht eingerichtet")

        def worker():
            done, value, error = run_with_deadline(call, 20)
            ok, msg = _result_from_deadline(done, value, error)
            self.after(0, lambda: self._finish_b2_test(ok, msg))
        threading.Thread(target=worker, daemon=True).start()

    def settings_init_schema(self):
        if guard_active(self.store.data):
            messagebox.showwarning("Weihnachtsmarkt-Schutz", "04.–13.12. sind Schema-/Core-Zugriffe auf das Backup-Ziel gesperrt.", parent=self); return
        profile = self.selected_profile()
        if not profile:
            return
        valid = self._validate_profile(profile)
        if not valid:
            return
        dsn = valid[0]
        if not self._activity_start("Schema / Core wird geprüft und abgeglichen …", (getattr(self, "btn_core_test", None),)):
            return

        def worker():
            done, _, error = run_with_deadline(lambda: initialize_schema(dsn), 30)
            if done and error is None:
                self.after(0, self._finish_core_test)
            else:
                self.after(0, lambda m=str(error or "Zeitüberschreitung"): self._finish_core_error(m))
        threading.Thread(target=worker, daemon=True).start()

    def settings_test_kc(self):
        if not self.save_communication(quiet=True):
            return
        client = make_kc_client(self.store)
        if not client:
            messagebox.showwarning("PC Backup Vault", "Gerät ist noch nicht registriert. Bitte zuerst registrieren / Pairing-Code ausführen.", parent=self); return
        if not self._activity_start("KC Kopplung wird getestet …", (getattr(self, "btn_kc_test", None),)):
            return

        def worker():
            done, value, error = run_with_deadline(client.test, 15)
            ok, msg = _result_from_deadline(done, value, error)
            self.after(0, lambda: self._finish_kc_test(ok, msg))
        threading.Thread(target=worker, daemon=True).start()

    SettingsWindowClass.test_profile = settings_test_profile
    SettingsWindowClass.test_b2 = settings_test_b2
    SettingsWindowClass.init_schema = settings_init_schema
    SettingsWindowClass.test_kc_communication = settings_test_kc

    # ------------------------------------------------------------------
    # Status popups: same window, same buttons, plus a small inline progress
    # row. All direct tests have a deadline and late results are ignored.
    # ------------------------------------------------------------------
    def open_system_status(self, key):
        names = {
            "neon": "Neon / Metadatenbank", "b2": "Backblaze B2", "vault": "Lokaler Tresor",
            "scheduler": "Windows Scheduler", "verify": "Verify / TÜV", "kc": "KC Kommunikation",
        }
        win = tk.Toplevel(self)
        win.title(f"Systemstatus – {names.get(key, key)}")
        win.geometry("680x390")
        win.minsize(620, 360)
        win.transient(self)
        box = ttk.Frame(win, padding=14); box.pack(fill="both", expand=True)
        ttk.Label(box, text=names.get(key, key), font=("Segoe UI", 16, "bold")).pack(anchor="w")
        statebox = ttk.LabelFrame(box, text="Aktueller Zustand", padding=10); statebox.pack(fill="x", pady=(12, 8))
        state_now = self._system_states.get(key, {})
        level = state_now.get("level", getattr(self.indicators.get(key), "level", "unknown"))
        detail = state_now.get("detail", getattr(self.indicators.get(key), "detail", "–"))
        lbl = ttk.Label(statebox, text=f"Status: {str(level).upper()}\n{detail}", justify="left", wraplength=620)
        lbl.pack(anchor="w")
        ttk.Label(box, text="Die obere LED zeigt den Zustand. Die kleine untere LED blinkt bei echtem Datenverkehr.", wraplength=630).pack(anchor="w", pady=(0, 8))

        last_lbl = None
        if key == "kc":
            try:
                from kc_communication import recent_history
                hist = recent_history(1)
            except Exception:
                hist = []
            text = "Letzter Versand: –"
            if hist:
                h = hist[0]
                text = f"Letzter Versand: {h.get('delivery', '–')}"
                if h.get("channels"):
                    text += f" · Kanäle: {', '.join(h.get('channels') or [])}"
                result = str(h.get("result") or h.get("error") or "")
                if result == "Keine Kanaldetails vom Server" and str(h.get("delivery") or "").upper() in {"SENT", "PARTIAL"}:
                    result = "Server hatte den Versand bestätigt; ältere Client-Version zeigte keine Kanaldetails."
                if result:
                    text += "\n" + result
            last_lbl = ttk.Label(box, text=text, justify="left", wraplength=630)
            last_lbl.pack(anchor="w", pady=(0, 8))

        progress_frame = ttk.Frame(box); progress_frame.pack(fill="x", pady=(3, 9))
        progress = ttk.Progressbar(progress_frame, mode="determinate", maximum=100, value=0)
        progress.pack(side="left", fill="x", expand=True)
        pct_label = ttk.Label(progress_frame, text="0 %", width=6, anchor="e"); pct_label.pack(side="left", padx=(8, 0))
        elapsed_label = ttk.Label(progress_frame, text="Bereit", width=16, anchor="e"); elapsed_label.pack(side="left", padx=(8, 0))

        actions = ttk.Frame(box); actions.pack(fill="x", pady=(4, 0))
        buttons = []
        run_state = {"id": 0, "started": None, "budget": 15, "running": False}

        def set_buttons(state):
            for button in buttons:
                try:
                    button.config(state=state)
                except Exception:
                    pass

        def tick(run_id):
            if not win.winfo_exists() or not run_state["running"] or run_state["id"] != run_id:
                return
            elapsed = time.monotonic() - run_state["started"]
            pct = timed_percent(elapsed, run_state["budget"])
            progress["value"] = pct; pct_label.config(text=f"{pct} %")
            elapsed_label.config(text=f"Laufzeit {int(elapsed // 60):02d}:{int(elapsed % 60):02d}")
            win.after(150, lambda: tick(run_id))

        def finish(run_id, ok, msg, level_override=None):
            if not win.winfo_exists() or run_state["id"] != run_id:
                return
            run_state["running"] = False
            progress["value"] = 100; pct_label.config(text="100 %")
            elapsed = time.monotonic() - run_state["started"] if run_state["started"] else 0
            elapsed_label.config(text=f"Dauer {int(elapsed // 60):02d}:{int(elapsed % 60):02d}")
            level_text = level_override or ("ok" if ok else "error")
            lbl.config(text=f"Status: {level_text.upper()}\n{msg}")
            try:
                self._set_indicator(key, level_text, msg)
            except Exception:
                pass
            set_buttons("normal")

        def start_test(label, callable_, budget=15, level_resolver=None):
            run_state["id"] += 1; run_id = run_state["id"]
            run_state.update(started=time.monotonic(), budget=budget, running=True)
            progress["value"] = 0; pct_label.config(text="0 %"); elapsed_label.config(text="Laufzeit 00:00")
            lbl.config(text=f"Status: PRÜFUNG LÄUFT …\n{label}")
            set_buttons("disabled"); tick(run_id)

            def worker():
                done, value, error = run_with_deadline(callable_, budget)
                ok, msg = _result_from_deadline(done, value, error)
                level_value = level_resolver(ok, msg) if level_resolver else None
                self.after(0, lambda: finish(run_id, ok, msg, level_value))
            threading.Thread(target=worker, daemon=True).start()

        def status_callable():
            if key == "neon":
                dsn = self.active_dsn()
                return test_connection(dsn) if dsn else (False, "Datenbankzugang fehlt")
            if key == "b2":
                cfg = self.store.get_b2_runtime_config()
                if not cfg.get("configured"):
                    return False, "B2 nicht vollständig eingerichtet"
                store = make_b2_store(cfg)
                return store.ping() if store else (False, "B2 nicht eingerichtet")
            if key == "vault":
                return (True, "Recovery-/Master-Key im Windows-Tresor") if self.master_key() else (False, "Master-Key fehlt")
            if key == "scheduler":
                plans = [p for p in self.store.data.get("plans", []) if p.get("enabled") and p.get("schedule_type") != "MANUAL"]
                if not plans:
                    return True, "Keine automatische Aufgabe konfiguriert"
                ok, msg = task_status(plans[0])
                return ok, "Windows-Aufgabe vorhanden" if ok else ((msg or "Aufgabe nicht gefunden").splitlines()[0])
            if key == "verify":
                dsn = self.active_dsn()
                if not dsn:
                    return False, "Ohne Neon nicht prüfbar"
                vr = recent_verifications(dsn, 1)
                tv = recent_tuev_checks(dsn, 50)
                latest_tv = []
                if tv:
                    stamp = tv[0][0]; latest_tv = [row for row in tv if row[0] == stamp]
                if vr and vr[0][5] == "FAIL": return False, "Letzte Verifizierung: FAIL"
                if any(row[3] == "FAIL" for row in latest_tv): return False, "Letzter TÜV enthält Fehler"
                if (vr and vr[0][5] == "WARN") or any(row[3] == "WARN" for row in latest_tv): return True, "Letzte Integritätsprüfung mit Warnung"
                return True, "Letzte Integritätsprüfung ohne Fehler" if vr or tv else "Noch kein Verify/TÜV-Nachweis"
            if key == "kc":
                client = make_kc_client(self.store)
                return client.test() if client else (False, "Gerät noch nicht registriert / gekoppelt")
            return False, "Unbekannter Test"

        def status_level(ok, msg):
            low = str(msg).lower()
            if key == "kc" and ("pending" in low or "pairing" in low):
                return "warn"
            if key in ("scheduler", "verify") and ok and ("keine" in low or "warn" in low or "noch kein" in low):
                return "warn"
            return "ok" if ok else "error"

        btn_test = ttk.Button(actions, text="Verbindung testen", command=lambda: start_test("Verbindung wird geprüft …", status_callable, 15, status_level))
        btn_test.pack(side="left"); buttons.append(btn_test)

        if key == "kc":
            def channel_test(channel):
                client = make_kc_client(self.store)
                if not client:
                    finish(run_state["id"], False, "KC Kommunikation ist nicht vollständig eingerichtet.")
                    return

                def done_level(ok, msg):
                    return "ok" if ok else "error"

                def call():
                    return client.diagnose_channel(channel)

                start_test(f"{channel.upper()} wird einzeln geprüft …", call, 15, done_level)

            btn_push = ttk.Button(actions, text="Push testen", command=lambda: channel_test("push")); btn_push.pack(side="left", padx=(6, 0)); buttons.append(btn_push)
            btn_email = ttk.Button(actions, text="E-Mail testen", command=lambda: channel_test("email")); btn_email.pack(side="left", padx=(6, 0)); buttons.append(btn_email)
            btn_settings = ttk.Button(actions, text="KC Einstellungen", command=lambda: [win.destroy(), self.open_settings(tab="communication")]); btn_settings.pack(side="left", padx=6)

        ttk.Button(actions, text="Schließen", command=win.destroy).pack(side="right")

    AppClass.open_system_status = open_system_status

    # ------------------------------------------------------------------
    # TÜV: keep one window and report controls, replace the indefinite spinner
    # with a time/percent bar and deadline.
    # ------------------------------------------------------------------
    def open_tuev(self):
        if guard_active(self.store.data):
            messagebox.showwarning("Weihnachtsmarkt-Schutz", "04.–13.12. wird kein Online-TÜV gegen Neon ausgeführt."); return
        profile = self.active_profile(); dsn = self.active_dsn()
        if not profile or not dsn:
            messagebox.showwarning("PC Backup Vault", "Bitte zuerst Datenbankzugang einrichten."); return
        win = tk.Toplevel(self); win.title("TÜV / Architekturprüfung"); win.geometry("1040x630")
        body = ttk.Frame(win, padding=10); body.pack(fill="both", expand=True)
        tree = ttk.Treeview(body, columns=("code", "name", "result", "details"), show="headings")
        for col, title, width in (("code", "Code", 90), ("name", "Prüfung", 240), ("result", "Ergebnis", 90), ("details", "Details", 650)):
            tree.heading(col, text=title); tree.column(col, width=width)
        y = ttk.Scrollbar(body, orient="vertical", command=tree.yview); x = ttk.Scrollbar(body, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=y.set, xscrollcommand=x.set); tree.grid(row=0, column=0, sticky="nsew"); y.grid(row=0, column=1, sticky="ns"); x.grid(row=1, column=0, sticky="ew")
        body.rowconfigure(0, weight=1); body.columnconfigure(0, weight=1)
        status = ttk.Frame(win, padding=(10, 0, 10, 10)); status.pack(fill="x")
        lbl = ttk.Label(status, text="TÜV wird ausgeführt …"); lbl.pack(anchor="w")
        progress_row = ttk.Frame(status); progress_row.pack(fill="x", pady=(5, 5))
        bar = ttk.Progressbar(progress_row, mode="determinate", maximum=100, value=0); bar.pack(side="left", fill="x", expand=True)
        pct = ttk.Label(progress_row, text="0 %", width=6, anchor="e"); pct.pack(side="left", padx=(8, 0))
        tm = ttk.Label(progress_row, text="Laufzeit: 00:00", width=18, anchor="e"); tm.pack(side="left", padx=(8, 0))
        buttons = ttk.Frame(status); buttons.pack(fill="x")
        tuev_state = {"checks": []}; started = time.monotonic(); running = {"value": True}

        def report_text():
            checks = tuev_state["checks"]
            fails = sum(1 for c in checks if c[2] == "FAIL"); warns = sum(1 for c in checks if c[2] == "WARN")
            lines = ["PC BACKUP VAULT – TÜV / ARCHITEKTURPRÜFUNG", f"Erstellt: {datetime.now():%d.%m.%Y %H:%M:%S}", f"Prüfungen: {len(checks)} · Fehler: {fails} · Warnungen: {warns}", ""]
            lines.extend(f"{c[0]} | {c[2]} | {c[1]} | {c[3]}" for c in checks)
            return "\n".join(lines) + "\n"

        def copy_report():
            if not tuev_state["checks"]: return
            win.clipboard_clear(); win.clipboard_append(report_text()); win.update()
            messagebox.showinfo("PC Backup Vault", "TÜV-Report wurde kopiert.", parent=win)

        def print_report():
            if not tuev_state["checks"]: return
            try:
                fd, path = tempfile.mkstemp(prefix="PC_Backup_Vault_TUEV_", suffix=".txt"); os.close(fd)
                Path(path).write_text(report_text(), encoding="utf-8"); os.startfile(path, "print")
            except Exception as exc:
                messagebox.showerror("PC Backup Vault", f"Drucken nicht möglich:\n{exc}", parent=win)

        def send_report():
            checks = tuev_state["checks"]
            if not checks: return
            fails = sum(1 for c in checks if c[2] == "FAIL"); warns = sum(1 for c in checks if c[2] == "WARN")
            self.notify_kc("tuev_failed", "PC Backup Vault – TÜV-Report", f"{len(checks)} Prüfungen · {fails} Fehler · {warns} Warnungen", "ERROR" if fails else ("WARN" if warns else "INFO"), {"failedChecks": fails, "warningChecks": warns, "status": "FAIL" if fails else ("WARN" if warns else "PASS")})
            messagebox.showinfo("PC Backup Vault", "TÜV-Report wurde zur Übergabe an KC Kommunikation eingestellt.", parent=win)

        ttk.Button(buttons, text="Kopieren", command=copy_report).pack(side="right", padx=(6, 0))
        ttk.Button(buttons, text="Drucken", command=print_report).pack(side="right", padx=(6, 0))
        ttk.Button(buttons, text="An KC Kommunikation", command=send_report).pack(side="right", padx=(6, 0))

        def tick():
            if not win.winfo_exists() or not running["value"]: return
            elapsed = time.monotonic() - started; value = timed_percent(elapsed, 90)
            bar["value"] = value; pct.config(text=f"{value} %"); tm.config(text=f"Laufzeit: {int(elapsed // 60):02d}:{int(elapsed % 60):02d}")
            win.after(200, tick)
        tick()

        def work():
            done, value, error = run_with_deadline(lambda: list(ui_module.run_tuev(dsn, bool(self.master_key()), bool(self.store.data.get("recovery_key_exported")), profile, self.store.data) or []), 90)
            checks = list(value or []) if done and error is None else [("TUEV-TIMEOUT", "TÜV/Core-Gesamttest", "FAIL", str(error or "Zeitüberschreitung"))]

            def finish():
                if not win.winfo_exists(): return
                running["value"] = False; bar["value"] = 100; pct.config(text="100 %")
                elapsed = time.monotonic() - started; tm.config(text=f"Dauer: {int(elapsed // 60):02d}:{int(elapsed % 60):02d}")
                tuev_state["checks"] = checks
                for item in checks: tree.insert("", "end", values=item)
                fails = sum(1 for c in checks if c[2] == "FAIL"); warns = sum(1 for c in checks if c[2] == "WARN")
                lbl.config(text=f"TÜV abgeschlossen: {len(checks)} Prüfungen · {fails} Fehler · {warns} Warnungen")
                if fails or warns:
                    self.notify_kc("tuev_failed", "Backup-TÜV mit Hinweis", f"{fails} Fehler · {warns} Warnungen", "ERROR" if fails else "WARN")
                self.refresh_system_status()
            self.after(0, finish)
        threading.Thread(target=work, daemon=True).start()

    AppClass.open_tuev = open_tuev

    # ------------------------------------------------------------------
    # Consolidated "Alle Tests": actual stage progress (not just animation),
    # plus per-network deadline. No additional progress window is opened.
    # ------------------------------------------------------------------
    def run_all_tests(self):
        if guard_active(self.store.data):
            messagebox.showwarning("Weihnachtsmarkt-Schutz", "04.–13.12. wird kein Online-Gesamttest gegen Neon ausgeführt.", parent=self); return
        profile = self.active_profile(); dsn = self.active_dsn()
        if not profile or not dsn:
            messagebox.showwarning("PC Backup Vault", "Bitte zuerst den Datenbankzugang einrichten.", parent=self); return

        win = tk.Toplevel(self); win.title("PC Backup Vault – Alle Tests"); win.geometry("1120x750"); win.minsize(920, 600); win.transient(self)
        head = ttk.Frame(win, padding=(14, 12, 14, 8)); head.pack(fill="x")
        ttk.Label(head, text="Alle Tests durchführen", font=("Segoe UI", 16, "bold")).pack(anchor="w")
        summary = ttk.Label(head, text="Prüfung läuft …"); summary.pack(anchor="w", pady=(5, 0))
        progress_row = ttk.Frame(head); progress_row.pack(fill="x", pady=(8, 0))
        bar = ttk.Progressbar(progress_row, mode="determinate", maximum=100, value=0); bar.pack(side="left", fill="x", expand=True)
        pct = ttk.Label(progress_row, text="0 %", width=6, anchor="e"); pct.pack(side="left", padx=(8, 0))
        tm = ttk.Label(progress_row, text="Laufzeit: 00:00", width=18, anchor="e"); tm.pack(side="left", padx=(8, 0))
        body = ttk.Frame(win, padding=(14, 0, 14, 8)); body.pack(fill="both", expand=True)
        tree = ttk.Treeview(body, columns=("code", "name", "result", "details"), show="headings")
        for col, title, width in (("code", "Prüfung", 90), ("name", "Einzeltest", 250), ("result", "Ergebnis", 80), ("details", "Details", 620)):
            tree.heading(col, text=title); tree.column(col, width=width, anchor="center" if col == "result" else "w")
        sy = ttk.Scrollbar(body, orient="vertical", command=tree.yview); sx = ttk.Scrollbar(body, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=sy.set, xscrollcommand=sx.set); tree.grid(row=0, column=0, sticky="nsew"); sy.grid(row=0, column=1, sticky="ns"); sx.grid(row=1, column=0, sticky="ew")
        body.rowconfigure(0, weight=1); body.columnconfigure(0, weight=1)
        footer = ttk.Frame(win, padding=(14, 4, 14, 12)); footer.pack(fill="x")
        report_holder = {"text": ""}; started = time.monotonic(); running = {"value": True}
        ttk.Label(footer, text="TÜV/Core plus Live-Tests. Langsame Onlinetests werden zeitlich begrenzt und blockieren das Fenster nicht dauerhaft.", wraplength=650).pack(side="left", fill="x", expand=True)
        button_box = ttk.Frame(footer); button_box.pack(side="right", padx=(10, 0))
        btn_copy = ttk.Button(button_box, text="📋 Tests kopieren", state="disabled"); btn_copy.pack(side="left", padx=(0, 6))
        btn_save = ttk.Button(button_box, text="💾 Datei erstellen", state="disabled"); btn_save.pack(side="left", padx=(0, 6))
        ttk.Button(button_box, text="Schließen", command=win.destroy).pack(side="left")
        try: self.btn_all_tests_v180.configure(state="disabled")
        except Exception: pass

        def set_progress(value, text):
            def apply():
                if not win.winfo_exists(): return
                value2 = max(0, min(100, int(value))); bar["value"] = value2; pct.config(text=f"{value2} %"); summary.config(text=text)
            self.after(0, apply)

        def tick():
            if not win.winfo_exists() or not running["value"]: return
            elapsed = time.monotonic() - started; tm.config(text=f"Laufzeit: {int(elapsed // 60):02d}:{int(elapsed % 60):02d}"); win.after(250, tick)
        tick()

        def make_report(checks):
            passed = sum(1 for c in checks if str(c[2]).upper() == "PASS"); warns = sum(1 for c in checks if str(c[2]).upper() == "WARN"); failed = sum(1 for c in checks if str(c[2]).upper() == "FAIL")
            overall = "FEHLER" if failed else ("WARNUNGEN" if warns else "PASS")
            lines = ["PC BACKUP VAULT – ALLE TESTS", "=" * 48, f"Erstellt: {datetime.now().astimezone():%d.%m.%Y %H:%M:%S}", f"Gesamtergebnis: {overall}", f"Prüfungen: {len(checks)} · PASS: {passed} · Warnungen: {warns} · Fehler: {failed}", ""]
            lines.extend(f"{code} | {name} | {result} | {details}" for code, name, result, details in checks)
            return "\n".join(lines), overall, passed, warns, failed

        def copy_report():
            if not report_holder["text"]: return
            self.clipboard_clear(); self.clipboard_append(report_holder["text"]); self.update_idletasks()
            messagebox.showinfo("PC Backup Vault", "Testergebnis wurde kopiert.", parent=win)

        def save_report():
            if not report_holder["text"]: return
            path = filedialog.asksaveasfilename(parent=win, title="Testergebnis speichern", defaultextension=".txt", initialfile=f"PC_Backup_Vault_Alle_Tests_{datetime.now():%Y-%m-%d_%H-%M-%S}.txt", filetypes=[("Textdatei", "*.txt"), ("Alle Dateien", "*.*")])
            if path:
                Path(path).write_text(report_holder["text"], encoding="utf-8")
                messagebox.showinfo("PC Backup Vault", f"Testergebnis gespeichert:\n\n{path}", parent=win)
        btn_copy.config(command=copy_report); btn_save.config(command=save_report)

        def deadline_tuple(callable_, timeout, fail_code, fail_name, fail_result="FAIL"):
            done, value, error = run_with_deadline(callable_, timeout)
            if not done or error is not None:
                return None, (fail_code, fail_name, fail_result, str(error or "Zeitüberschreitung"))
            return value, None

        def work():
            checks = []
            set_progress(5, "TÜV/Core-Prüfungen laufen …")
            value, failure = deadline_tuple(lambda: list(ui_module.run_tuev(dsn, bool(self.master_key()), bool(self.store.data.get("recovery_key_exported")), profile, self.store.data) or []), 90, "ALL-999", "TÜV/Core-Gesamttest")
            if failure: checks.append(failure)
            else: checks.extend(list(value or []))

            set_progress(65, "Neon Live-Verbindung wird geprüft …")
            value, failure = deadline_tuple(lambda: test_connection(dsn), 15, "LED-NEON", "Neon Live-Verbindung")
            if failure: checks.append(failure)
            else: checks.append(("LED-NEON", "Neon Live-Verbindung", "PASS" if value[0] else "FAIL", value[1]))

            set_progress(74, "Backblaze B2 wird geprüft …")
            b2cfg = self.store.get_b2_runtime_config()
            if not b2cfg.get("configured"):
                checks.append(("LED-B2", "B2 Live-Verbindung", "WARN", "B2 nicht vollständig eingerichtet"))
            else:
                def b2call():
                    store = make_b2_store(b2cfg); return store.ping() if store else (False, "B2 nicht eingerichtet")
                value, failure = deadline_tuple(b2call, 20, "LED-B2", "B2 Live-Verbindung")
                if failure: checks.append(failure)
                else: checks.append(("LED-B2", "B2 Live-Verbindung", "PASS" if value[0] else "FAIL", value[1]))

            set_progress(84, "Lokaler Tresor wird geprüft …")
            has_key = bool(self.master_key()); checks.append(("LED-VAULT", "Lokaler Tresor", "PASS" if has_key else "FAIL", "Tresorschlüssel vorhanden" if has_key else "Tresorschlüssel fehlt"))

            set_progress(88, "Windows Scheduler wird geprüft …")
            plans = list(self.store.data.get("plans", []) or [])
            if not plans:
                checks.append(("LED-SCHED", "Windows Scheduler", "WARN", "Noch kein Backup-Plan vorhanden"))
            else:
                value, failure = deadline_tuple(lambda: task_status(plans[0]), 10, "LED-SCHED", "Windows Scheduler", "WARN")
                if failure: checks.append(failure)
                else:
                    ok, msg = value; checks.append(("LED-SCHED", "Windows Scheduler", "PASS" if ok else "WARN", "Windows-Aufgabe vorhanden" if ok else ((msg or "Aufgabe nicht gefunden").splitlines()[0])))

            set_progress(93, "KC Kommunikation wird geprüft …")
            cfg = self.store.data.get("kc_communication") or {}
            if not cfg.get("enabled"):
                checks.append(("LED-KC", "KC Kommunikation Live", "WARN", "KC Kommunikation ist ausgeschaltet"))
            else:
                client = make_kc_client(self.store)
                if not client:
                    checks.append(("LED-KC", "KC Kommunikation Live", "WARN", "Gerät noch nicht registriert / gekoppelt"))
                else:
                    value, failure = deadline_tuple(client.test, 15, "LED-KC", "KC Kommunikation Live")
                    if failure: checks.append(failure)
                    else:
                        ok, msg = value; low = str(msg).lower(); level = "PASS" if ok else ("WARN" if "pending" in low or "pairing" in low else "FAIL"); checks.append(("LED-KC", "KC Kommunikation Live", level, msg))

            set_progress(98, "Testergebnis wird zusammengestellt …")
            report, overall, passed, warns, failed = make_report(checks)

            def finish():
                try: self.btn_all_tests_v180.configure(state="normal")
                except Exception: pass
                try: self.refresh_system_status()
                except Exception: pass
                if not win.winfo_exists(): return
                running["value"] = False; bar["value"] = 100; pct.config(text="100 %")
                elapsed = time.monotonic() - started; tm.config(text=f"Dauer: {int(elapsed // 60):02d}:{int(elapsed % 60):02d}")
                report_holder["text"] = report
                summary.config(text=f"Gesamtergebnis: {overall} · Prüfungen: {len(checks)} · PASS: {passed} · Warnungen: {warns} · Fehler: {failed}")
                for item in checks: tree.insert("", "end", values=item)
                btn_copy.config(state="normal"); btn_save.config(state="normal")
            self.after(0, finish)
        threading.Thread(target=work, daemon=True).start()

    AppClass.run_all_tests_v180 = run_all_tests
