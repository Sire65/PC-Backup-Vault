from __future__ import annotations

from tkinter import BOTH, X, ttk

from .source_candidates import build_source_candidate_rows


class SourceCandidatesTab(ttk.Frame):
    """Read-only view of plausible local PC Backup Vault source roots."""

    def __init__(self, master, *, get_scan_items=None):
        super().__init__(master)
        self.get_scan_items = get_scan_items or (lambda: [])
        toolbar = ttk.Frame(self)
        toolbar.pack(fill=X, padx=8, pady=8)
        ttk.Button(toolbar, text="Aus Festplatten-Analyse übernehmen", command=self.refresh).pack(side="left")
        self.status = ttk.Label(toolbar, text="Noch nicht ausgewertet")
        self.status.pack(side="left", padx=(12, 0))

        cols = ("risk", "state", "version", "required", "extra", "root", "reason")
        self.tree = ttk.Treeview(self, columns=cols, show="headings")
        headings = {
            "risk": "Ampel", "state": "Status", "version": "Version", "required": "Pflichtdateien",
            "extra": "Zusatzdateien", "root": "Quellordner", "reason": "Bewertung",
        }
        widths = {"risk": 70, "state": 170, "version": 80, "required": 100, "extra": 100, "root": 330, "reason": 520}
        for col in cols:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], anchor="w")
        self.tree.pack(fill=BOTH, expand=True, padx=8, pady=(0, 8))

    def refresh(self):
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        rows = build_source_candidate_rows(self.get_scan_items())
        for row in rows:
            self.tree.insert("", "end", values=(
                row["risk"], row["state"], row["version_hint"], row["required_summary"],
                row["extra_files"], row["root"], row["reason"],
            ))
        if rows:
            self.status.configure(text=f"{len(rows)} lokale Quellstand-Kandidaten gefunden – noch keine Merge-Freigabe")
        else:
            self.status.configure(text="Keine plausiblen Quellstand-Kandidaten im aktuellen Scan gefunden")
