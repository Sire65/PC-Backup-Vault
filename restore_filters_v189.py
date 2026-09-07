from __future__ import annotations

from datetime import datetime, timedelta
import tkinter as tk
from tkinter import ttk, messagebox


def _parse_date(value: str):
    value = (value or "").strip()
    if not value:
        return None
    return datetime.strptime(value, "%d.%m.%Y")


def _record_datetime(row):
    value = row[10]
    if hasattr(value, "replace"):
        try:
            return value.replace(tzinfo=None)
        except Exception:
            pass
    return None


def _size_match(size: int, choice: str) -> bool:
    size = int(size or 0)
    mb = 1024 * 1024
    if choice == "Unter 1 MB":
        return size < mb
    if choice == "1–10 MB":
        return mb <= size < 10 * mb
    if choice == "10–100 MB":
        return 10 * mb <= size < 100 * mb
    if choice == "Über 100 MB":
        return size >= 100 * mb
    return True


def apply_restore_filters_v189(RestoreAssistantClass, file_group_func, fmt_size_func):
    """Add multi-criteria, user-friendly filtering to restore step 1 without touching restore logic."""

    def step_what(self):
        self.subtitle.configure(text="Schritt 1 von 4 – Welche Sicherung möchten Sie zurückholen?")
        ttk.Label(self.body, text="Sicherungen finden", font=("Segoe UI", 15, "bold")).pack(anchor="w")
        ttk.Label(
            self.body,
            text="Sie können mehrere Filter kombinieren. Standardmäßig wird pro Datei nur der neueste Sicherungsstand gezeigt.",
            wraplength=1000,
        ).pack(anchor="w", pady=(4, 9))

        # Persistent filter values when the user navigates back from later steps.
        state = getattr(self, "_restore_filter_state_v189", {})
        self.search = tk.StringVar(value=state.get("search", ""))
        self.filter_var = tk.StringVar(value=state.get("type", "Alle Dateitypen"))
        self.date_var = tk.StringVar(value=state.get("date", "Alle Zeiträume"))
        self.date_from_var = tk.StringVar(value=state.get("date_from", ""))
        self.date_to_var = tk.StringVar(value=state.get("date_to", ""))
        self.path_var = tk.StringVar(value=state.get("path", "Alle Verzeichnisse"))
        self.plan_var = tk.StringVar(value=state.get("plan", "Alle Pläne"))
        self.storage_var = tk.StringVar(value=state.get("storage", "Alle Speicher"))
        self.size_var = tk.StringVar(value=state.get("size", "Alle Größen"))
        self.version_view_var = tk.StringVar(value=state.get("versions", "Neueste je Datei"))

        # Build human-readable filter values from decrypted metadata already loaded locally.
        folders = sorted({self.decoded.get(str(r[0]), {}).get("path", "") for r in self.records if self.decoded.get(str(r[0]), {}).get("path", "")}, key=str.casefold)
        plans = sorted({str(r[13]) for r in self.records if r[13]}, key=str.casefold)
        backends = sorted({str(r[14]) for r in self.records if r[14]}, key=str.casefold)
        storage_labels = {"B2": "Backblaze B2", "NEON": "Neon", "FILESYSTEM": "USB / Laufwerk / NAS"}
        storage_values = ["Alle Speicher"] + [storage_labels.get(x, x) for x in backends]
        self._storage_reverse_v189 = {storage_labels.get(x, x): x for x in backends}

        filters = ttk.LabelFrame(self.body, text="Filter", padding=9)
        filters.pack(fill="x", pady=(0, 8))

        ttk.Label(filters, text="Suche Datei / Pfad:").grid(row=0, column=0, sticky="w", padx=(0, 5), pady=3)
        ent = ttk.Entry(filters, textvariable=self.search, width=34)
        ent.grid(row=0, column=1, columnspan=3, sticky="ew", padx=(0, 12), pady=3)

        ttk.Label(filters, text="Zeitraum:").grid(row=0, column=4, sticky="w", padx=(0, 5), pady=3)
        ttk.Combobox(
            filters, textvariable=self.date_var, state="readonly", width=18,
            values=("Alle Zeiträume", "Heute", "Letzte 7 Tage", "Letzte 30 Tage", "Dieses Jahr", "Benutzerdefiniert"),
        ).grid(row=0, column=5, sticky="ew", pady=3)

        ttk.Label(filters, text="Von:").grid(row=1, column=0, sticky="w", padx=(0, 5), pady=3)
        ttk.Entry(filters, textvariable=self.date_from_var, width=12).grid(row=1, column=1, sticky="w", pady=3)
        ttk.Label(filters, text="Bis:").grid(row=1, column=2, sticky="w", padx=(8, 5), pady=3)
        ttk.Entry(filters, textvariable=self.date_to_var, width=12).grid(row=1, column=3, sticky="w", pady=3)
        ttk.Label(filters, text="Format TT.MM.JJJJ", foreground="#64748b").grid(row=1, column=4, columnspan=2, sticky="w", padx=(8, 0), pady=3)

        ttk.Label(filters, text="Verzeichnis:").grid(row=2, column=0, sticky="w", padx=(0, 5), pady=3)
        path_combo = ttk.Combobox(filters, textvariable=self.path_var, state="readonly", values=["Alle Verzeichnisse"] + folders)
        path_combo.grid(row=2, column=1, columnspan=3, sticky="ew", padx=(0, 12), pady=3)
        ttk.Label(filters, text="Dateityp:").grid(row=2, column=4, sticky="w", padx=(0, 5), pady=3)
        ttk.Combobox(
            filters, textvariable=self.filter_var, state="readonly", width=18,
            values=("Alle Dateitypen", "Dokumente", "Bilder", "Medien", "Andere"),
        ).grid(row=2, column=5, sticky="ew", pady=3)

        ttk.Label(filters, text="Backup-Plan:").grid(row=3, column=0, sticky="w", padx=(0, 5), pady=3)
        ttk.Combobox(filters, textvariable=self.plan_var, state="readonly", values=["Alle Pläne"] + plans).grid(row=3, column=1, sticky="ew", pady=3)
        ttk.Label(filters, text="Speicher:").grid(row=3, column=2, sticky="w", padx=(8, 5), pady=3)
        ttk.Combobox(filters, textvariable=self.storage_var, state="readonly", values=storage_values).grid(row=3, column=3, sticky="ew", pady=3)
        ttk.Label(filters, text="Größe:").grid(row=3, column=4, sticky="w", padx=(8, 5), pady=3)
        ttk.Combobox(
            filters, textvariable=self.size_var, state="readonly", width=18,
            values=("Alle Größen", "Unter 1 MB", "1–10 MB", "10–100 MB", "Über 100 MB"),
        ).grid(row=3, column=5, sticky="ew", pady=3)

        ttk.Label(filters, text="Sicherungsstände:").grid(row=4, column=0, sticky="w", padx=(0, 5), pady=3)
        ttk.Combobox(
            filters, textvariable=self.version_view_var, state="readonly",
            values=("Neueste je Datei", "Alle Sicherungsstände"),
        ).grid(row=4, column=1, sticky="ew", pady=3)
        ttk.Button(filters, text="Filter zurücksetzen", command=self._reset_restore_filters_v189).grid(row=4, column=5, sticky="e", pady=3)

        filters.columnconfigure(1, weight=1)
        filters.columnconfigure(3, weight=1)
        filters.columnconfigure(5, weight=1)

        table = ttk.Frame(self.body); table.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(
            table, columns=("file", "folder", "date", "plan", "storage", "size"), show="headings", selectmode="extended"
        )
        for c, t, w in [
            ("file", "Dateiname", 260), ("folder", "Verzeichnis", 330), ("date", "Sicherung", 145),
            ("plan", "Plan", 120), ("storage", "Speicher", 105), ("size", "Größe", 85),
        ]:
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="e" if c == "size" else "w")
        y = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        x = ttk.Scrollbar(table, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=y.set, xscrollcommand=x.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        y.grid(row=0, column=1, sticky="ns")
        x.grid(row=1, column=0, sticky="ew")
        table.rowconfigure(0, weight=1); table.columnconfigure(0, weight=1)

        self.info_lbl = ttk.Label(self.body, text="", padding=(0, 6, 0, 0))
        self.info_lbl.pack(anchor="w")

        for var in (self.search, self.filter_var, self.date_var, self.date_from_var, self.date_to_var,
                    self.path_var, self.plan_var, self.storage_var, self.size_var, self.version_view_var):
            var.trace_add("write", lambda *_: self._refresh_files())
        self.tree.bind("<Double-1>", lambda _e: self.next())
        self._refresh_files()
        ent.focus_set()

    def _save_filter_state(self):
        self._restore_filter_state_v189 = {
            "search": self.search.get(), "type": self.filter_var.get(), "date": self.date_var.get(),
            "date_from": self.date_from_var.get(), "date_to": self.date_to_var.get(), "path": self.path_var.get(),
            "plan": self.plan_var.get(), "storage": self.storage_var.get(), "size": self.size_var.get(),
            "versions": self.version_view_var.get(),
        }

    def _reset_restore_filters_v189(self):
        self.search.set("")
        self.filter_var.set("Alle Dateitypen")
        self.date_var.set("Alle Zeiträume")
        self.date_from_var.set("")
        self.date_to_var.set("")
        self.path_var.set("Alle Verzeichnisse")
        self.plan_var.set("Alle Pläne")
        self.storage_var.set("Alle Speicher")
        self.size_var.set("Alle Größen")
        self.version_view_var.set("Neueste je Datei")

    def _date_bounds(self):
        now = datetime.now()
        choice = self.date_var.get()
        start = end = None
        if choice == "Heute":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=1)
        elif choice == "Letzte 7 Tage":
            start = now - timedelta(days=7)
        elif choice == "Letzte 30 Tage":
            start = now - timedelta(days=30)
        elif choice == "Dieses Jahr":
            start = datetime(now.year, 1, 1)
        elif choice == "Benutzerdefiniert":
            try:
                start = _parse_date(self.date_from_var.get())
                end_day = _parse_date(self.date_to_var.get())
                end = end_day + timedelta(days=1) if end_day else None
            except ValueError:
                return "INVALID", None
        return start, end

    def _refresh_files(self):
        if not hasattr(self, "tree"):
            return
        _save_filter_state(self)
        q = self.search.get().strip().casefold()
        file_type = self.filter_var.get()
        folder_filter = self.path_var.get()
        plan_filter = self.plan_var.get()
        storage_filter = self.storage_var.get()
        size_filter = self.size_var.get()
        show_all_versions = self.version_view_var.get() == "Alle Sicherungsstände"
        start, end = _date_bounds(self)

        previous_selection = set(self.tree.selection())
        for item in self.tree.get_children():
            self.tree.delete(item)

        if start == "INVALID":
            self.info_lbl.configure(text="⚠ Benutzerdefiniertes Datum bitte als TT.MM.JJJJ eingeben.")
            return

        shown = 0
        seen = set()
        active_filters = 0
        if q: active_filters += 1
        if file_type != "Alle Dateitypen": active_filters += 1
        if self.date_var.get() != "Alle Zeiträume": active_filters += 1
        if folder_filter != "Alle Verzeichnisse": active_filters += 1
        if plan_filter != "Alle Pläne": active_filters += 1
        if storage_filter != "Alle Speicher": active_filters += 1
        if size_filter != "Alle Größen": active_filters += 1
        if show_all_versions: active_filters += 1

        for r in self.records:
            fid = str(r[0])
            meta = self.decoded.get(fid, {})
            name = meta.get("name", "")
            folder = meta.get("path", "")
            ext = meta.get("ext", "")
            plan = str(r[13] or "")
            backend = str(r[14] or "")
            dt = _record_datetime(r)

            if not show_all_versions:
                key = (folder.casefold(), name.casefold())
                if key in seen:
                    continue
                seen.add(key)

            if q and q not in f"{name} {folder} {plan}".casefold():
                continue
            if file_type != "Alle Dateitypen" and file_group_func(ext) != file_type:
                continue
            if folder_filter != "Alle Verzeichnisse" and folder != folder_filter:
                continue
            if plan_filter != "Alle Pläne" and plan != plan_filter:
                continue
            if storage_filter != "Alle Speicher" and backend != self._storage_reverse_v189.get(storage_filter, storage_filter):
                continue
            if not _size_match(r[5], size_filter):
                continue
            if dt is not None:
                if start and dt < start:
                    continue
                if end and dt >= end:
                    continue
            elif start or end:
                continue

            stamp = r[10].strftime("%d.%m.%Y %H:%M") if hasattr(r[10], "strftime") else str(r[10])
            storage = {"B2": "Backblaze B2", "NEON": "Neon", "FILESYSTEM": "USB / NAS"}.get(backend, backend)
            self.tree.insert("", "end", iid=fid, values=(name, folder, stamp, plan or "–", storage or "–", fmt_size_func(r[5])))
            if fid in previous_selection or fid in self.selected_ids:
                self.tree.selection_add(fid)
            shown += 1

        mode_text = "alle Sicherungsstände" if show_all_versions else "neueste je Datei"
        self.info_lbl.configure(text=f"{shown} Treffer · {active_filters} Filter aktiv · Ansicht: {mode_text}")

    RestoreAssistantClass.step_what = step_what
    RestoreAssistantClass._save_filter_state_v189 = _save_filter_state
    RestoreAssistantClass._reset_restore_filters_v189 = _reset_restore_filters_v189
    RestoreAssistantClass._date_bounds_v189 = _date_bounds
    RestoreAssistantClass._refresh_files = _refresh_files
