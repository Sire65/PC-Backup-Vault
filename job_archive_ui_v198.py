from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from archive_restore_v198 import restore_archived_job
from job_archive_v198 import archive_path, get_job, list_jobs, refresh_archive
from unified_reporting_v193 import human_size


def _fmt_dt(value) -> str:
    if not value:
        return "–"
    try:
        return datetime.fromisoformat(str(value)).astimezone().strftime("%d.%m.%Y %H:%M:%S")
    except Exception:
        return str(value)


class JobArchiveWindow(tk.Toplevel):
    def __init__(self, app, recent_jobs_func):
        super().__init__(app)
        self.app = app
        self.recent_jobs_func = recent_jobs_func
        self.title("PC Backup Vault – Job-Archiv")
        self.geometry("1460x760")
        self.minsize(1100, 620)
        self.transient(app)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        head = ttk.Frame(self, padding=(14, 12, 14, 8)); head.pack(fill="x")
        ttk.Label(head, text="Job-Archiv", font=("Segoe UI", 20, "bold")).pack(side="left")
        ttk.Label(head, text="Alle Sicherungsläufe – B2, Neon, HiDrive, NAS und Dateispeicher", font=("Segoe UI", 10)).pack(side="left", padx=(16, 0))
        ttk.Button(head, text="Aktualisieren", command=self.refresh).pack(side="right")
        ttk.Button(head, text="Schließen", command=self.destroy).pack(side="right", padx=(0, 6))

        controls = ttk.Frame(self, padding=(14, 0, 14, 8)); controls.pack(fill="x")
        ttk.Label(controls, text="Suche:").pack(side="left")
        self.search_var = tk.StringVar()
        entry = ttk.Entry(controls, textvariable=self.search_var, width=42)
        entry.pack(side="left", fill="x", expand=True, padx=(6, 12))
        self.info = ttk.Label(controls, text="")
        self.info.pack(side="right")

        box = ttk.Frame(self, padding=(14, 0, 14, 8)); box.pack(fill="both", expand=True)
        box.columnconfigure(0, weight=1); box.rowconfigure(0, weight=1)
        columns = ("date","job","status","source","target","files","size","verify","restore")
        self.tree = ttk.Treeview(box, columns=columns, show="headings", selectmode="browse")
        specs = (
            ("date","Datum / Uhrzeit",145), ("job","Job-ID",235), ("status","Status",80),
            ("source","Quelle",260), ("target","Ziel",210), ("files","Dateien",70),
            ("size","Datenmenge",95), ("verify","Prüfung",145), ("restore","Restore",105),
        )
        for c,t,w in specs:
            self.tree.heading(c, text=t); self.tree.column(c, width=w, minwidth=60, anchor="w")
        sy = ttk.Scrollbar(box, orient="vertical", command=self.tree.yview)
        sx = ttk.Scrollbar(box, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        self.tree.grid(row=0,column=0,sticky="nsew"); sy.grid(row=0,column=1,sticky="ns"); sx.grid(row=1,column=0,sticky="ew")
        self.tree.bind("<Double-1>", lambda _e: self.restore_selected())

        foot = ttk.Frame(self, padding=(14, 8, 14, 14)); foot.pack(fill="x")
        self.details = ttk.Label(foot, text="Job auswählen. Doppelklick startet die Wiederherstellung.", wraplength=980, justify="left")
        self.details.pack(side="left", fill="x", expand=True)
        ttk.Button(foot, text="♻ Ausgewählten Job wiederherstellen", command=self.restore_selected).pack(side="right")
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._show_details())
        self.search_var.trace_add("write", lambda *_: self._render())
        self.rows = []
        self.refresh()
        entry.focus_set()

    def refresh(self):
        counts = refresh_archive(self.app.store, self.app.active_dsn(), self.recent_jobs_func)
        self.rows = list_jobs(self.app.store)
        self.info.config(text=f"Archiv: {counts['total']} Job(s) · Datei: {archive_path(self.app.store).name}")
        self._render()

    def _render(self):
        q = self.search_var.get().strip().casefold()
        self.tree.delete(*self.tree.get_children())
        shown = 0
        for r in self.rows:
            hay = " ".join(str(r.get(k) or "") for k in ("job_id","source_label","target_label","status","backend_label","plan_name")).casefold()
            if q and q not in hay:
                continue
            jid = str(r.get("job_id"))
            self.tree.insert("", "end", iid=jid, values=(
                _fmt_dt(r.get("started_at") or r.get("reported_at")), jid,
                r.get("status") or "–", r.get("source_label") or "–", r.get("target_label") or "–",
                int(r.get("file_count") or 0), human_size(r.get("original_bytes")),
                r.get("verification_status") or "–", r.get("restore_status") or "noch nicht",
            ))
            shown += 1
        self.info.config(text=f"{shown} von {len(self.rows)} Job(s) · Archiv: {archive_path(self.app.store).name}")

    def _selected_job_id(self):
        sel = self.tree.selection()
        return str(sel[0]) if sel else None

    def _show_details(self):
        jid = self._selected_job_id()
        if not jid:
            return
        r = get_job(self.app.store, jid) or {}
        self.details.config(text=(
            f"{r.get('source_to_target') or '–'}   |   Status {r.get('status') or '–'}   |   "
            f"{int(r.get('file_count') or 0)} Dateien · {human_size(r.get('original_bytes'))}   |   "
            f"Verifizierung: {r.get('verification_status') or '–'}"
        ))

    def restore_selected(self):
        jid = self._selected_job_id()
        if not jid:
            messagebox.showinfo("Job-Archiv", "Bitte zuerst einen Job auswählen.", parent=self)
            return
        job = get_job(self.app.store, jid) or {}
        kind = str((job.get("locator") or {}).get("kind") or "").upper()
        backend = str(job.get("backend_label") or "").lower()
        if kind == "NEON" or backend in {"neon", "backblaze b2"}:
            self.app._archive_restore_job_id = jid
            self.app.open_restore_assistant()
            return
        destination = filedialog.askdirectory(parent=self, title=f"Wiederherstellungsziel für Job {jid}")
        if not destination:
            return
        self.details.config(text=f"Wiederherstellung von {jid} läuft …")
        def work():
            try:
                result = restore_archived_job(self.app, jid, Path(destination))
                self.after(0, lambda: self._restore_done(jid, result))
            except RuntimeError as exc:
                if str(exc) == "DATABASE_RESTORE":
                    self.after(0, lambda: self._database_restore(jid))
                else:
                    self.after(0, lambda e=exc: self._restore_failed(jid, e))
            except Exception as exc:
                self.after(0, lambda e=exc: self._restore_failed(jid, e))
        threading.Thread(target=work, name=f"pbv-archive-restore-{jid[:8]}", daemon=True).start()

    def _database_restore(self, jid):
        self.app._archive_restore_job_id = jid
        self.app.open_restore_assistant()

    def _restore_done(self, jid, result):
        self.refresh()
        messagebox.showinfo(
            "Wiederherstellung erfolgreich",
            f"Job {jid} wurde wiederhergestellt.\n\n{result['files']} Datei(en) · {human_size(result['bytes'])}\nZiel: {result['destination']}\n\nSHA-256-Prüfung: PASS",
            parent=self,
        )

    def _restore_failed(self, jid, exc):
        self.refresh()
        messagebox.showerror("Wiederherstellung fehlgeschlagen", f"Job {jid}\n\n{exc}", parent=self)


def apply_job_archive_v198(AppClass, RestoreAssistantClass, WorkbenchClass, recent_jobs_func):
    if getattr(AppClass, "_job_archive_v198", False):
        return

    original_app_build = AppClass._build
    def app_build(self):
        original_app_build(self)
        self.open_job_archive = lambda: JobArchiveWindow(self, recent_jobs_func)
        try:
            parent = self.btn_backup.master
            ttk.Button(parent, text="🗄 Job-Archiv", command=self.open_job_archive).pack(side="left", padx=(0, 8), before=self.btn_backup)
        except Exception:
            pass
    AppClass._build = app_build

    original_load_records = RestoreAssistantClass._load_records
    def load_records(self):
        original_load_records(self)
        requested = str(getattr(self.app, "_archive_restore_job_id", "") or "")
        if not requested:
            return
        self.records = [r for r in self.records if len(r) > 1 and str(r[1]) == requested]
        valid = {str(r[0]) for r in self.records}
        self.decoded = {k:v for k,v in self.decoded.items() if k in valid}
        self.app._archive_restore_job_id = None
    RestoreAssistantClass._load_records = load_records

    original_workbench_build = WorkbenchClass._build
    def workbench_build(self):
        original_workbench_build(self)
        try:
            ttk.Button(self, text="🗄 Job-Archiv", command=lambda: JobArchiveWindow(self.app, recent_jobs_func)).place(relx=0.985, y=18, anchor="ne")
        except Exception:
            pass
    WorkbenchClass._build = workbench_build

    AppClass._job_archive_v198 = True
