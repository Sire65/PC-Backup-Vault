from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from kc_backup_program_registry import KCProgramRegistry
from kc_backup_source_discovery import discover_candidates


class SourceDiscoveryWindow(tk.Toplevel):
    """Read-only candidate preview. It cannot mutate the program registry."""

    def __init__(self, master, *, registry: KCProgramRegistry):
        super().__init__(master)
        self.registry = registry
        self.title("Backup Central – KC Quellen finden")
        self.geometry("1120x680")
        self.minsize(900, 560)
        self._build()

    def _build(self):
        head = ttk.Frame(self, padding=12)
        head.pack(fill="x")
        ttk.Label(head, text="KC Quellen finden", font=("Segoe UI", 17, "bold")).pack(side="left")
        ttk.Label(head, text="Nur Vorschläge · keine automatische Übernahme").pack(side="left", padx=16)
        ttk.Button(head, text="Suchordner wählen …", command=self._choose_root).pack(side="right")

        info = ttk.Label(
            self,
            text=("Die Suche liest nur Dateinamen und Ordnerstrukturen unter dem von Ihnen gewählten Stammordner. "
                  "Sie verändert keine Datei, folgt keinen Symlinks und trägt keine Quelle automatisch ein."),
            wraplength=1050,
            padding=(12, 0, 12, 10),
        )
        info.pack(fill="x")

        self.tree = ttk.Treeview(
            self,
            columns=("source", "score", "path", "reason"),
            show="tree headings",
            height=23,
        )
        for key, text, width in (
            ("#0", "Programm", 150),
            ("source", "Sicherungsbereich", 190),
            ("score", "Treffer", 70),
            ("path", "Vorschlag", 430),
            ("reason", "Warum gefunden", 250),
        ):
            self.tree.heading(key, text=text)
            self.tree.column(key, width=width, anchor="w")
        self.tree.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        self.tree.bind("<Double-1>", lambda _e: self._copy_selected())

        bottom = ttk.Frame(self, padding=(12, 0, 12, 12))
        bottom.pack(fill="x")
        self.status = ttk.Label(bottom, text="Noch kein Suchordner gewählt.")
        self.status.pack(side="left")
        ttk.Button(bottom, text="Pfad kopieren", command=self._copy_selected).pack(side="right")

    def _choose_root(self):
        root = filedialog.askdirectory(title="Stammordner für read-only KC-Quellensuche wählen", parent=self)
        if not root:
            return
        self.status.config(text="Suche läuft …")
        self.update_idletasks()
        try:
            candidates = discover_candidates(root, self.registry.all())
        except Exception as exc:
            self.status.config(text="Suche fehlgeschlagen.")
            messagebox.showerror("KC Quellen finden", str(exc), parent=self)
            return
        self.tree.delete(*self.tree.get_children())
        by_program = {p.program_id: p for p in self.registry.all()}
        source_labels = {
            (p.program_id, s.source_id): s.label
            for p in self.registry.all()
            for s in p.sources
        }
        for index, item in enumerate(candidates):
            program = by_program[item.program_id]
            self.tree.insert(
                "", "end", iid=f"candidate-{index}", text=program.display_name,
                values=(source_labels.get((item.program_id, item.source_id), item.source_id),
                        f"{item.score}%", str(item.path), item.reason),
            )
        self.status.config(
            text=(f"{len(candidates)} Vorschlag/Vorschläge gefunden unter: {root}"
                  if candidates else f"Keine ausreichend sicheren Vorschläge gefunden unter: {root}")
        )

    def _copy_selected(self):
        selected = self.tree.selection()
        if not selected:
            return
        values = self.tree.item(selected[0], "values")
        if len(values) < 3:
            return
        path = str(values[2])
        self.clipboard_clear()
        self.clipboard_append(path)
        self.status.config(text=f"Pfad kopiert: {path}")
