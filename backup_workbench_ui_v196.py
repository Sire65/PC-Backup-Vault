from __future__ import annotations

import tkinter as tk
from tkinter import ttk


def _safe_cloud_path(row: dict) -> str:
    """Hide provider-internal home paths in the normal operator UI."""
    if row.get("account_id"):
        return "PC_Backup_Vault"
    return str(row.get("path") or "–")


def _save_restore_selftest(store, var):
    store.data["restore_selftest_after_backup"] = bool(var.get())
    store.save()


def apply_backup_workbench_ui_v196(WorkbenchClass):
    """UI-only polish. Existing backup/restore/media logic stays untouched."""
    if getattr(WorkbenchClass, "_ui_v196", False):
        return WorkbenchClass

    original_media_rows = WorkbenchClass._media_rows
    original_media_selected = WorkbenchClass._media_selected

    def _return_to_main(self, _event=None):
        """Close only the workbench and reliably return focus to the main window."""
        try:
            self._close()
        finally:
            app = getattr(self, "app", None)
            if app is not None:
                try:
                    app.deiconify()
                except Exception:
                    pass
                try:
                    app.lift()
                except Exception:
                    pass
                try:
                    app.focus_force()
                except Exception:
                    pass
        return "break"

    def _build(self):
        self.configure(padx=0, pady=0)
        try:
            self.state("zoomed")
        except Exception:
            self.geometry("1440x900")
        self.minsize(1180, 720)
        self.protocol("WM_DELETE_WINDOW", self._return_to_main_v197)
        self.bind("<Escape>", self._return_to_main_v197)
        self.bind("<Alt-F4>", self._return_to_main_v197)

        shell = ttk.Frame(self, padding=(18, 14, 18, 14))
        shell.pack(fill="both", expand=True)
        shell.columnconfigure(0, weight=1, uniform="pane")
        shell.columnconfigure(1, weight=0)
        shell.columnconfigure(2, weight=1, uniform="pane")
        shell.rowconfigure(1, weight=1)

        head = ttk.Frame(shell)
        head.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 12))
        ttk.Label(head, text="Sichern & Wiederherstellen", font=("Segoe UI", 20, "bold")).pack(side="left")
        ttk.Label(head, text="  1 Quelle wählen   →   2 Ziel wählen   →   3 Optionen prüfen   →   Backup starten", font=("Segoe UI", 10)).pack(side="left", padx=(18, 0))
        ttk.Button(head, text="← Zurück zum Hauptfenster", command=self._return_to_main_v197).pack(side="right")

        left = ttk.LabelFrame(shell, text="1 · QUELLE", padding=10)
        left.grid(row=1, column=0, sticky="nsew")
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)
        ttk.Label(left, text="Laufwerk, Ordner oder einzelne Dateien auswählen", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 8))

        treebox = ttk.Frame(left)
        treebox.grid(row=1, column=0, sticky="nsew")
        treebox.columnconfigure(0, weight=1); treebox.rowconfigure(0, weight=1)
        self.src_tree = ttk.Treeview(treebox, columns=("path",), show="tree headings", selectmode="extended")
        self.src_tree.heading("#0", text="Datei / Ordner")
        self.src_tree.heading("path", text="Pfad")
        self.src_tree.column("#0", width=280, minwidth=190)
        self.src_tree.column("path", width=380, minwidth=220)
        sy = ttk.Scrollbar(treebox, orient="vertical", command=self.src_tree.yview)
        sx = ttk.Scrollbar(treebox, orient="horizontal", command=self.src_tree.xview)
        self.src_tree.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        self.src_tree.grid(row=0, column=0, sticky="nsew"); sy.grid(row=0, column=1, sticky="ns"); sx.grid(row=1, column=0, sticky="ew")
        self.src_tree.bind("<<TreeviewOpen>>", self._expand_source)
        self.src_tree.bind("<Double-1>", lambda _e: self.add_source_selection())

        src_actions = ttk.Frame(left)
        src_actions.grid(row=2, column=0, sticky="ew", pady=(9, 5))
        ttk.Button(src_actions, text="✓ Markierung übernehmen", command=self.add_source_selection).pack(side="left")
        ttk.Button(src_actions, text="＋ Dateien…", command=self.pick_files).pack(side="left", padx=6)
        ttk.Button(src_actions, text="＋ Ordner…", command=self.pick_folder).pack(side="left")

        ttk.Label(left, text="Ausgewählte Quellen", font=("Segoe UI", 9, "bold")).grid(row=3, column=0, sticky="w", pady=(4, 3))
        selected_box = ttk.Frame(left)
        selected_box.grid(row=4, column=0, sticky="ew")
        selected_box.columnconfigure(0, weight=1)
        self.source_list = tk.Listbox(selected_box, height=5, exportselection=False)
        self.source_list.grid(row=0, column=0, sticky="ew")
        ttk.Button(selected_box, text="Entfernen", command=self.remove_source).grid(row=0, column=1, sticky="ns", padx=(6, 0))

        mid = ttk.Frame(shell, padding=(16, 0))
        mid.grid(row=1, column=1, sticky="ns")
        ttk.Label(mid, text="→", font=("Segoe UI", 34, "bold")).pack(pady=(155, 0))
        ttk.Label(mid, text="SICHERN", font=("Segoe UI", 9, "bold")).pack()
        ttk.Separator(mid, orient="horizontal").pack(fill="x", pady=18)
        ttk.Button(mid, text="← Wiederherstellen", command=self.restore, width=18).pack()

        right = ttk.LabelFrame(shell, text="2 · ZIEL", padding=10)
        right.grid(row=1, column=2, sticky="nsew")
        right.columnconfigure(0, weight=1); right.rowconfigure(1, weight=1)
        ttk.Label(right, text="Sicherungsmedium auswählen – Häkchen schaltet ein oder aus", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 8))

        target_treebox = ttk.Frame(right)
        target_treebox.grid(row=1, column=0, sticky="nsew")
        target_treebox.columnconfigure(0, weight=1); target_treebox.rowconfigure(0, weight=1)
        self.media_tree = ttk.Treeview(target_treebox, columns=("active", "type", "name", "path"), show="headings", selectmode="browse")
        specs = (("active", "Aktiv", 55), ("type", "Medium", 110), ("name", "Bezeichnung", 210), ("path", "Ziel", 280))
        for c, t, w in specs:
            self.media_tree.heading(c, text=t); self.media_tree.column(c, width=w, minwidth=50, anchor="w")
        ty = ttk.Scrollbar(target_treebox, orient="vertical", command=self.media_tree.yview)
        tx = ttk.Scrollbar(target_treebox, orient="horizontal", command=self.media_tree.xview)
        self.media_tree.configure(yscrollcommand=ty.set, xscrollcommand=tx.set)
        self.media_tree.grid(row=0, column=0, sticky="nsew"); ty.grid(row=0, column=1, sticky="ns"); tx.grid(row=1, column=0, sticky="ew")
        self.media_tree.bind("<<TreeviewSelect>>", lambda _e: self._media_selected())
        self.media_tree.bind("<Button-1>", self._media_click, add="+")

        targetbar = ttk.Frame(right)
        targetbar.grid(row=2, column=0, sticky="ew", pady=(9, 0))
        ttk.Button(targetbar, text="📁 Zielordner / neues Ziel", command=self.choose_target_folder).pack(side="left")
        ttk.Button(targetbar, text="Cloud-Ziele verwalten", command=lambda: self.app.open_settings(tab="cloud")).pack(side="left", padx=6)
        ttk.Button(targetbar, text="Dateispeicher verwalten", command=lambda: self.app.open_settings(tab="storage")).pack(side="left")
        self.target_info = ttk.Label(right, text="Noch kein Ziel gewählt.", justify="left", wraplength=620)
        self.target_info.grid(row=3, column=0, sticky="ew", pady=(9, 0))

        options = ttk.LabelFrame(shell, text="3 · SICHERHEIT & PRÜFUNG", padding=10)
        options.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(12, 8))
        options.columnconfigure(0, weight=1); options.columnconfigure(1, weight=1); options.columnconfigure(2, weight=1); options.columnconfigure(3, weight=1)
        self.encrypt_var = tk.BooleanVar(value=True)
        self.sha_var = tk.BooleanVar(value=True)
        self.report_var = tk.BooleanVar(value=True)
        self.verify_var = tk.BooleanVar(value=bool(self.store.data.get("auto_quick_verify_after_backup", True)))
        self.restore_selftest_var = tk.BooleanVar(value=bool(self.store.data.get("restore_selftest_after_backup", True)))

        ttk.Label(options, text="✓ AES-256-GCM Verschlüsselung", font=("Segoe UI", 9, "bold")).grid(row=0, column=0, sticky="w", padx=(0, 14))
        ttk.Label(options, text="immer aktiv", foreground="#64748b").grid(row=1, column=0, sticky="w")
        ttk.Label(options, text="✓ SHA-256 Integrität", font=("Segoe UI", 9, "bold")).grid(row=0, column=1, sticky="w", padx=(0, 14))
        ttk.Label(options, text="immer aktiv", foreground="#64748b").grid(row=1, column=1, sticky="w")
        ttk.Label(options, text="✓ Quelle → Ziel im Bericht", font=("Segoe UI", 9, "bold")).grid(row=0, column=2, sticky="w", padx=(0, 14))
        ttk.Label(options, text="immer aktiv", foreground="#64748b").grid(row=1, column=2, sticky="w")

        choice = ttk.Frame(options)
        choice.grid(row=0, column=3, rowspan=2, sticky="w")
        self.verify_check = ttk.Checkbutton(choice, text="Backup automatisch verifizieren", variable=self.verify_var)
        self.verify_check.pack(anchor="w")
        ttk.Checkbutton(choice, text="Wiederherstellungs-Selbsttest", variable=self.restore_selftest_var,
                        command=lambda: _save_restore_selftest(self.store, self.restore_selftest_var)).pack(anchor="w", pady=(4, 0))

        run = ttk.LabelFrame(shell, text="4 · BACKUP", padding=10)
        run.grid(row=3, column=0, columnspan=3, sticky="ew")
        run.columnconfigure(1, weight=1)
        self.lamp = tk.Canvas(run, width=44, height=44, highlightthickness=0)
        self.lamp.grid(row=0, column=0, rowspan=2, sticky="w")
        self.lamp_dot = self.lamp.create_oval(7, 7, 37, 37, fill="#94a3b8", outline="#64748b")
        self.status = ttk.Label(run, text="Bereit – Quelle und Ziel wählen.", font=("Segoe UI", 10, "bold"), wraplength=820)
        self.status.grid(row=0, column=1, sticky="ew", padx=(8, 12))
        self.speed = ttk.Label(run, text="Geschwindigkeit: –    Spitze: –    Restzeit: –")
        self.speed.grid(row=1, column=1, sticky="w", padx=(8, 12), pady=(3, 0))
        self.progress = ttk.Progressbar(run, maximum=100, value=0, length=280)
        self.progress.grid(row=0, column=2, rowspan=2, sticky="e", padx=(0, 12))
        self.btn_start = ttk.Button(run, text="▶  BACKUP STARTEN", command=self.start_backup, width=22)
        self.btn_start.grid(row=0, column=3, rowspan=2, sticky="e")

    def _media_rows(self):
        rows = original_media_rows(self)
        for row in rows:
            if row.get("account_id"):
                row["path"] = _safe_cloud_path(row)
        return rows

    def _media_selected(self):
        original_media_selected(self)
        r = getattr(self, "selected_media", None)
        if not r:
            return
        safe_path = _safe_cloud_path(r)
        state = "aktiv" if r.get("enabled") else "für Datensicherungen ausgeschaltet"
        self.target_info.config(text=f"Ausgewählt: {r.get('name') or 'Ziel'}\nZiel: {safe_path}\nStatus: {state}")
        if r.get("code") in ("B2", "NEON"):
            self.verify_check.configure(state="normal")
        else:
            self.verify_check.configure(state="disabled")
            self.verify_var.set(False)

    WorkbenchClass._build = _build
    WorkbenchClass._media_rows = _media_rows
    WorkbenchClass._media_selected = _media_selected
    WorkbenchClass._return_to_main_v197 = _return_to_main
    WorkbenchClass._ui_v196 = True
    return WorkbenchClass
