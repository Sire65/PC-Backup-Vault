from __future__ import annotations

import os
import threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from backup_engine import collect_paths
from cloud_targets_v191 import cloud_accounts, cloud_account, ensure_filesystem_bridge
from storage_v180 import DISPLAY, CODE


BUILTIN_MEDIA = {
    "B2": "Backblaze B2 + Neon-Core",
    "NEON": "Neon – nur Kleinmengen",
}


def ensure_media_config(store):
    changed = False
    flags = store.data.setdefault("backup_media_enabled", {})
    for code in BUILTIN_MEDIA:
        if code not in flags:
            flags[code] = True; changed = True
    for target in store.data.setdefault("filesystem_targets", []):
        if "enabled" not in target:
            target["enabled"] = True; changed = True
    if changed:
        store.save()


def builtin_enabled(store, code: str) -> bool:
    ensure_media_config(store)
    return bool(store.data.get("backup_media_enabled", {}).get(str(code).upper(), True))


def set_builtin_enabled(store, code: str, enabled: bool):
    ensure_media_config(store)
    store.data["backup_media_enabled"][str(code).upper()] = bool(enabled)
    store.save()


def target_enabled(store, target: dict | None) -> bool:
    if not target:
        return False
    ensure_media_config(store)
    if not bool(target.get("enabled", True)):
        return False
    account_id = str(target.get("cloud_account_id") or "")
    if account_id:
        account = cloud_account(store, account_id)
        return bool(account and account.get("enabled", True))
    return True


def set_target_enabled(store, target_id: str, enabled: bool) -> int:
    ensure_media_config(store)
    target = next((t for t in store.data.get("filesystem_targets", []) if t.get("id") == target_id), None)
    if not target:
        return 0
    target["enabled"] = bool(enabled)
    if not enabled and store.data.get("active_filesystem_target_id") == target_id:
        store.data["active_filesystem_target_id"] = None
    affected = sum(1 for p in store.data.get("plans", []) if p.get("filesystem_target_id") == target_id and p.get("enabled", True))
    store.save()
    return affected


def active_filesystem_targets(store):
    ensure_media_config(store)
    return [t for t in store.data.get("filesystem_targets", []) if target_enabled(store, t)]


def _human(n):
    x = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if x < 1024 or unit == "TB":
            return f"{x:.1f} {unit}"
        x /= 1024


def _drives():
    if hasattr(os, "listdrives"):
        try:
            return list(os.listdrives())
        except Exception:
            pass
    return [f"{c}:\\" for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if os.path.exists(f"{c}:\\")]


class BackupWorkbench(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.store = app.store
        ensure_media_config(self.store)
        self.title("PC Backup Vault – Sichern & Wiederherstellen")
        self.geometry("1380x820")
        self.minsize(1120, 700)
        self.selected_sources: list[str] = []
        self.selected_media = None
        self._started_here = False
        self._last_job_event = None
        self._build()
        self._load_source_browser()
        self.refresh_media()
        self.app._workbench_listener_v194 = self._on_progress
        self.app._workbench_event_listener_v194 = self._on_job_event
        self.protocol("WM_DELETE_WINDOW", self._close)

    def _build(self):
        head = ttk.Frame(self, padding=(14, 12, 14, 8)); head.pack(fill="x")
        ttk.Label(head, text="⇄ Sichern & Wiederherstellen", font=("Segoe UI", 19, "bold")).pack(side="left")
        ttk.Label(head, text="Quelle auswählen → Sicherungsmedium/Ziel wählen → Backup starten", font=("Segoe UI", 10)).pack(side="left", padx=16)

        main = ttk.Frame(self, padding=(12, 4, 12, 4)); main.pack(fill="both", expand=True)
        left = ttk.LabelFrame(main, text="1 · QUELLE – Laufwerke, Ordner und Dateien", padding=8)
        mid = ttk.Frame(main, width=110)
        right = ttk.LabelFrame(main, text="2 · ZIEL – Medium und Zielordner", padding=8)
        left.pack(side="left", fill="both", expand=True); mid.pack(side="left", fill="y", padx=10); right.pack(side="left", fill="both", expand=True)

        self.src_tree = ttk.Treeview(left, columns=("path",), show="tree headings", selectmode="extended", height=15)
        self.src_tree.heading("#0", text="Datei / Ordner"); self.src_tree.heading("path", text="Pfad")
        self.src_tree.column("#0", width=260); self.src_tree.column("path", width=360)
        sy = ttk.Scrollbar(left, orient="vertical", command=self.src_tree.yview); self.src_tree.configure(yscrollcommand=sy.set)
        self.src_tree.pack(side="left", fill="both", expand=True); sy.pack(side="left", fill="y")
        self.src_tree.bind("<<TreeviewOpen>>", self._expand_source)
        self.src_tree.bind("<Double-1>", lambda _e: self.add_source_selection())
        src_actions = ttk.Frame(left); src_actions.pack(fill="x", side="bottom", pady=(8, 0))
        ttk.Button(src_actions, text="✓ Auswahl übernehmen", command=self.add_source_selection).pack(side="left")
        ttk.Button(src_actions, text="＋ Dateien …", command=self.pick_files).pack(side="left", padx=5)
        ttk.Button(src_actions, text="＋ Ordner …", command=self.pick_folder).pack(side="left")

        self.source_list = tk.Listbox(left, height=6)
        self.source_list.pack(fill="x", side="bottom", pady=(8, 0))
        ttk.Button(left, text="Aus Auswahl entfernen", command=self.remove_source).pack(anchor="w", side="bottom")

        ttk.Label(mid, text="→", font=("Segoe UI", 34, "bold")).pack(pady=(150, 2))
        ttk.Label(mid, text="SICHERN", font=("Segoe UI", 9, "bold")).pack()
        ttk.Separator(mid, orient="horizontal").pack(fill="x", pady=16)
        ttk.Button(mid, text="←\nWiederherstellen", width=16, command=self.restore).pack()

        self.media_tree = ttk.Treeview(right, columns=("active", "type", "name", "path"), show="headings", selectmode="browse", height=13)
        specs = (("active", "Aktiv", 55), ("type", "Medium", 110), ("name", "Bezeichnung", 200), ("path", "Ziel / Ordner", 330))
        for c, t, w in specs:
            self.media_tree.heading(c, text=t); self.media_tree.column(c, width=w, anchor="w")
        self.media_tree.pack(fill="both", expand=True)
        self.media_tree.bind("<<TreeviewSelect>>", lambda _e: self._media_selected())
        self.media_tree.bind("<Button-1>", self._media_click, add="+")

        targetbar = ttk.Frame(right); targetbar.pack(fill="x", pady=(8, 0))
        ttk.Button(targetbar, text="📁 Zielordner wählen / neues Ziel", command=self.choose_target_folder).pack(side="left")
        ttk.Button(targetbar, text="Cloud-Ziele verwalten", command=lambda:self.app.open_settings(tab="cloud")).pack(side="left", padx=5)
        ttk.Button(targetbar, text="Dateispeicher verwalten", command=lambda:self.app.open_settings(tab="storage")).pack(side="left")
        self.target_info = ttk.Label(right, text="Noch kein Ziel gewählt.", wraplength=620, justify="left")
        self.target_info.pack(anchor="w", pady=(8, 0))

        options = ttk.LabelFrame(self, text="3 · Optionen", padding=10); options.pack(fill="x", padx=12, pady=(8, 4))
        self.encrypt_var = tk.BooleanVar(value=True); self.sha_var = tk.BooleanVar(value=True)
        self.verify_var = tk.BooleanVar(value=bool(self.store.data.get("auto_quick_verify_after_backup", True)))
        self.report_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(options, text="Verschlüsseln (AES-256-GCM · Pflicht)", variable=self.encrypt_var, state="disabled").pack(side="left", padx=(0, 18))
        ttk.Checkbutton(options, text="SHA-256 Integritätsprüfung (Pflicht)", variable=self.sha_var, state="disabled").pack(side="left", padx=(0, 18))
        self.verify_check = ttk.Checkbutton(options, text="Nach Sicherung automatisch verifizieren", variable=self.verify_var)
        self.verify_check.pack(side="left", padx=(0, 18))
        ttk.Checkbutton(options, text="Quelle → Ziel im Report", variable=self.report_var, state="disabled").pack(side="left")

        run = ttk.Frame(self, padding=(12, 6, 12, 12)); run.pack(fill="x")
        self.lamp = tk.Canvas(run, width=42, height=42, highlightthickness=0)
        self.lamp.pack(side="left"); self.lamp_dot = self.lamp.create_oval(7, 7, 35, 35, fill="#94a3b8", outline="#64748b")
        self.status = ttk.Label(run, text="Bereit – Quelle und Ziel wählen.", font=("Segoe UI", 10, "bold"), wraplength=690)
        self.status.pack(side="left", padx=8)
        self.speed = ttk.Label(run, text="Geschwindigkeit: –   Spitze: –   Restzeit: –")
        self.speed.pack(side="left", padx=14)
        self.progress = ttk.Progressbar(run, maximum=100, value=0, length=260); self.progress.pack(side="right", padx=(8, 0))
        self.btn_start = ttk.Button(run, text="▶ BACKUP STARTEN", command=self.start_backup)
        self.btn_start.pack(side="right")

    def _load_source_browser(self):
        self.src_tree.delete(*self.src_tree.get_children())
        for drive in _drives():
            iid = self.src_tree.insert("", "end", text=drive, values=(drive,), open=False)
            self.src_tree.insert(iid, "end", text="…", values=("",))

    def _expand_source(self, _event=None):
        item = self.src_tree.focus(); vals = self.src_tree.item(item, "values")
        if not vals: return
        path = str(vals[0]); children = self.src_tree.get_children(item)
        if len(children) == 1 and self.src_tree.item(children[0], "text") == "…":
            self.src_tree.delete(children[0])
            try:
                rows = sorted(Path(path).iterdir(), key=lambda p:(not p.is_dir(), p.name.lower()))
            except Exception:
                rows = []
            for p in rows[:2000]:
                try: isdir = p.is_dir()
                except Exception: isdir = False
                child = self.src_tree.insert(item, "end", text=("📁 " if isdir else "") + p.name, values=(str(p),))
                if isdir: self.src_tree.insert(child, "end", text="…", values=("",))

    def add_source_selection(self):
        for iid in self.src_tree.selection():
            vals = self.src_tree.item(iid, "values")
            if vals and vals[0] and vals[0] not in self.selected_sources:
                self.selected_sources.append(str(vals[0]))
        self._refresh_sources()

    def pick_files(self):
        for p in filedialog.askopenfilenames(parent=self, title="Quelldateien auswählen"):
            if p not in self.selected_sources: self.selected_sources.append(p)
        self._refresh_sources()

    def pick_folder(self):
        p = filedialog.askdirectory(parent=self, title="Quellordner auswählen")
        if p and p not in self.selected_sources: self.selected_sources.append(p)
        self._refresh_sources()

    def remove_source(self):
        idx = list(self.source_list.curselection())
        for i in reversed(idx): self.selected_sources.pop(i)
        self._refresh_sources()

    def _refresh_sources(self):
        self.source_list.delete(0, "end")
        for p in self.selected_sources: self.source_list.insert("end", p)

    def _media_rows(self):
        ensure_media_config(self.store)
        rows = [
            {"id":"builtin:B2", "code":"B2", "type":"Cloud", "name":BUILTIN_MEDIA["B2"], "path":"B2 Bucket", "enabled":builtin_enabled(self.store,"B2")},
            {"id":"builtin:NEON", "code":"NEON", "type":"Datenbank", "name":BUILTIN_MEDIA["NEON"], "path":"Neon", "enabled":builtin_enabled(self.store,"NEON")},
        ]
        for account in cloud_accounts(self.store):
            rows.append({"id":f"cloud:{account.get('id')}", "account_id":account.get("id"), "type":"Cloud", "name":account.get("name") or "Cloud", "path":account.get("root_path") or "–", "enabled":bool(account.get("enabled",True))})
        for t in self.store.data.get("filesystem_targets", []):
            if t.get("cloud_account_id"): continue
            rows.append({"id":f"fs:{t.get('id')}", "target_id":t.get("id"), "type":t.get("kind") or "Dateispeicher", "name":t.get("name") or "Backup-Ziel", "path":t.get("path") or "–", "enabled":bool(t.get("enabled",True))})
        return rows

    def refresh_media(self, select_id=None):
        self.media_tree.delete(*self.media_tree.get_children())
        for row in self._media_rows():
            self.media_tree.insert("", "end", iid=row["id"], values=("☑" if row["enabled"] else "☐", row["type"], row["name"], row["path"]))
        if select_id and self.media_tree.exists(select_id): self.media_tree.selection_set(select_id)

    def _row(self, iid=None):
        iid = iid or (self.media_tree.selection()[0] if self.media_tree.selection() else None)
        return next((r for r in self._media_rows() if r["id"] == iid), None)

    def _media_selected(self):
        self.selected_media = self._row()
        r = self.selected_media
        if not r: return
        self.target_info.config(text=f"Ausgewählt: {r['name']}\nZiel: {r['path']}\nStatus: {'aktiv' if r['enabled'] else 'für Datensicherungen ausgeschlossen'}")
        self.verify_check.configure(state="normal" if r.get("code") in ("B2","NEON") else "disabled")

    def _media_click(self, event):
        row_id = self.media_tree.identify_row(event.y); col = self.media_tree.identify_column(event.x)
        if row_id and col == "#1":
            self.after(1, lambda rid=row_id:self.toggle_media(rid))

    def toggle_media(self, iid):
        row = self._row(iid)
        if not row: return
        new = not row["enabled"]
        affected = 0
        if row.get("code"):
            set_builtin_enabled(self.store, row["code"], new)
        elif row.get("account_id"):
            account = cloud_account(self.store, row["account_id"])
            if account:
                account["enabled"] = new; self.store.save()
                affected = sum(1 for p in self.store.data.get("plans", []) if p.get("filesystem_target_id") == f"cloud-{row['account_id']}" and p.get("enabled",True))
                if not new and self.store.data.get("active_filesystem_target_id") == f"cloud-{row['account_id']}":
                    self.store.data["active_filesystem_target_id"] = None; self.store.save()
        elif row.get("target_id"):
            affected = set_target_enabled(self.store, row["target_id"], new)
        self.refresh_media(iid)
        if not new and affected:
            messagebox.showwarning("Sicherungsmedium deaktiviert", f"Das Medium wurde für Datensicherungen ausgeschlossen.\n\n{affected} aktiver Sicherungsplan verweist noch auf dieses Ziel und wird beim Start blockiert, bis ein anderes aktives Ziel gewählt wurde.", parent=self)
        self._media_selected()

    def choose_target_folder(self):
        row = self._row()
        if not row: messagebox.showinfo("Ziel", "Bitte zuerst ein Medium auswählen.", parent=self); return
        if row.get("account_id"):
            self.app.open_settings(tab="cloud")
            return
        if row.get("code"):
            messagebox.showinfo("Zielordner", "Bei diesem Medium wird der Zielbereich durch die bestehende Speicher-Konfiguration festgelegt.", parent=self); return
        target = next((t for t in self.store.data.get("filesystem_targets", []) if t.get("id") == row.get("target_id")), None)
        initial = (target or {}).get("path") or str(Path.home())
        p = filedialog.askdirectory(parent=self, title="Zielordner auswählen", initialdir=initial)
        if not p: return
        name = Path(p).name or p
        item = {"id":__import__("uuid").uuid4().hex, "name":name, "path":p, "kind":"NAS" if p.startswith("\\\\") else "ORDNER", "enabled":True}
        self.store.data.setdefault("filesystem_targets", []).append(item); self.store.save()
        self.refresh_media(f"fs:{item['id']}")
        self.selected_media = self._row(f"fs:{item['id']}"); self._media_selected()

    def _prepare_selected_target(self):
        row = self._row()
        if not row or not row.get("enabled"):
            raise RuntimeError("Bitte ein aktives Sicherungsmedium auswählen.")
        if row.get("code"):
            return row["code"], None
        if row.get("account_id"):
            target = ensure_filesystem_bridge(self.store, row["account_id"])
            self.store.data["active_filesystem_target_id"] = target.get("id"); self.store.save()
            return CODE, target
        target = next((t for t in self.store.data.get("filesystem_targets", []) if t.get("id") == row.get("target_id")), None)
        if not target_enabled(self.store, target): raise RuntimeError("Dieses Sicherungsmedium ist deaktiviert.")
        self.store.data["active_filesystem_target_id"] = target.get("id"); self.store.save()
        return CODE, target

    def start_backup(self):
        if not self.selected_sources:
            messagebox.showwarning("Backup", "Bitte links mindestens eine Datei oder einen Ordner auswählen.", parent=self); return
        try:
            code, _target = self._prepare_selected_target()
            paths = collect_paths(self.selected_sources)
            if not paths: raise RuntimeError("Die ausgewählten Quelldateien sind nicht erreichbar.")
        except Exception as exc:
            messagebox.showwarning("Backup", str(exc), parent=self); return
        self.app.selected = list(paths)
        if hasattr(self.app, "_refresh_tree"): self.app._refresh_tree()
        if code == CODE:
            self.app.payload_var.set(DISPLAY)
        else:
            display = getattr(__import__("ui"), "PAYLOAD_CODE_TO_DISPLAY", {}).get(code)
            if display: self.app.payload_var.set(display)
        if code in ("B2","NEON"):
            self.store.data["auto_quick_verify_after_backup"] = bool(self.verify_var.get()); self.store.save()
        self._started_here = True; self._last_job_event = None
        self._set_lamp("blue", "Backup läuft …")
        self.btn_start.configure(state="disabled")
        self.app.start_backup()
        self.after(250, self._poll_running)

    def _poll_running(self):
        running = bool(getattr(self.app, "_backup_running", False))
        try: msg = str(self.app.lbl_progress.cget("text"))
        except Exception: msg = "Backup läuft …"
        if running:
            self.status.config(text=msg or "Backup läuft …"); self.after(300, self._poll_running); return
        self.btn_start.configure(state="normal")
        if self._last_job_event in ("backup_failed", "verify_failed"):
            self._set_lamp("red", msg or "Backup fehlgeschlagen")
        elif self._last_job_event in ("backup_cancelled", "backup_warning"):
            self._set_lamp("yellow", msg or "Backup mit Hinweis beendet")
        elif self._last_job_event in ("backup_success", "backup_resumed") or "abgeschlossen" in msg.lower() or "erfolgreich" in msg.lower():
            self._set_lamp("green", msg or "Backup erfolgreich")
        else:
            self._set_lamp("yellow", msg or "Job beendet – Report prüfen")

    def _on_progress(self, done, total, msg, metrics=None):
        if not self.winfo_exists(): return
        metrics = metrics or {}; bdone = int(metrics.get("bytes_done") or 0); btotal = int(metrics.get("bytes_total") or 0)
        pct = (bdone / btotal * 100.0) if btotal else (done / max(1,total) * 100.0)
        self.progress.configure(value=max(0,min(100,pct)))
        self.status.config(text=msg)
        self.speed.config(text=f"Geschwindigkeit: {_human(metrics.get('speed_bps'))}/s   Spitze: {_human(metrics.get('peak_bps'))}/s   Restzeit: {int(metrics.get('eta_seconds') or 0)} s")

    def _on_job_event(self, event):
        self._last_job_event = event

    def _set_lamp(self, state, text):
        colors = {"blue":"#2563eb", "green":"#16a34a", "yellow":"#f59e0b", "red":"#dc2626", "gray":"#94a3b8"}
        self.lamp.itemconfigure(self.lamp_dot, fill=colors.get(state, colors["gray"])); self.status.config(text=text)

    def restore(self):
        try: self.app.open_restore_assistant()
        except Exception as exc: messagebox.showerror("Wiederherstellen", str(exc), parent=self)

    def _close(self):
        if getattr(self.app, "_workbench_listener_v194", None) == self._on_progress: self.app._workbench_listener_v194 = None
        if getattr(self.app, "_workbench_event_listener_v194", None) == self._on_job_event: self.app._workbench_event_listener_v194 = None
        self.destroy()


def apply_backup_workbench_v194(AppClass, storage_module):
    if getattr(AppClass, "_backup_workbench_v194", False): return
    ensure_original_target = storage_module._target

    def active_target(store, tid=None):
        target = ensure_original_target(store, tid)
        return target if target_enabled(store, target) else None
    storage_module._target = active_target

    original_build = AppClass._build
    original_start = AppClass.start_backup
    original_plan = AppClass._run_plan_v180
    original_progress = AppClass._progress
    original_notify = AppClass.notify_kc

    def _build(self):
        ensure_media_config(self.store); original_build(self)
        try:
            parent = self.btn_backup.master
            ttk.Button(parent, text="⇄ Sichern & Wiederherstellen", command=lambda:BackupWorkbench(self)).pack(side="left", padx=(0,8), before=self.btn_backup)
        except Exception:
            pass
        self.open_backup_workbench = lambda: BackupWorkbench(self)

    def _blocked_code(self, code):
        return code in ("B2","NEON") and not builtin_enabled(self.store, code)

    def start_backup(self, resume_checkpoint=None):
        if resume_checkpoint is None:
            try: code = self._selected_payload_code()
            except Exception: code = None
            if _blocked_code(self, code):
                messagebox.showwarning("Sicherungsmedium deaktiviert", f"{BUILTIN_MEDIA.get(code,code)} ist für Datensicherungen ausgeschlossen. Bitte ein aktives Ziel wählen.", parent=self); return
            if code == CODE and not storage_module._target(self.store):
                messagebox.showwarning("Sicherungsmedium deaktiviert", "Das ausgewählte Dateispeicher-/NAS-/Cloud-Ziel ist deaktiviert oder nicht verfügbar. Bitte ein aktives Ziel wählen.", parent=self); return
        return original_start(self, resume_checkpoint)

    def _run_plan_v180(self, plan):
        code = str(plan.get("payload_target") or "AUTO").upper()
        if _blocked_code(self, code):
            messagebox.showwarning("Sicherungsplan blockiert", f"Der Plan '{plan.get('name') or 'Backup'}' verwendet ein deaktiviertes Sicherungsmedium.", parent=self); return
        if code == CODE and not storage_module._target(self.store, plan.get("filesystem_target_id")):
            messagebox.showwarning("Sicherungsplan blockiert", f"Der Plan '{plan.get('name') or 'Backup'}' verweist auf ein deaktiviertes oder nicht verfügbares Ziel. Bitte zuerst ein aktives Ziel wählen.", parent=self); return
        return original_plan(self, plan)

    def _progress(self, done, total, msg, metrics=None):
        result = original_progress(self, done, total, msg, metrics)
        listener = getattr(self, "_workbench_listener_v194", None)
        if callable(listener):
            try: listener(done, total, msg, metrics)
            except Exception: pass
        return result

    def notify_kc(self, event, title, message, severity="INFO", details=None):
        result = original_notify(self, event, title, message, severity, details)
        listener = getattr(self, "_workbench_event_listener_v194", None)
        if callable(listener):
            try: listener(event)
            except Exception: pass
        return result

    AppClass._build = _build
    AppClass.start_backup = start_backup
    AppClass._run_plan_v180 = _run_plan_v180
    AppClass._progress = _progress
    AppClass.notify_kc = notify_kc
    AppClass._backup_workbench_v194 = True
