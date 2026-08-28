from __future__ import annotations

from tkinter import BOTH, END, LEFT, X, filedialog, messagebox, ttk
import json
from pathlib import Path

from .incremental_chat_merge import merge_findings


class ChangesSinceLastTab(ttk.Frame):
    """Shows only newly discovered chat/development evidence between inventories."""

    def __init__(self, master):
        super().__init__(master, padding=10)
        self.previous: list[dict] = []
        self.current: list[dict] = []
        self.result: dict = {"new_findings": [], "counts": {}}
        self._build()

    def _build(self):
        top = ttk.Frame(self)
        top.pack(fill=X)
        ttk.Label(top, text="Neu seit letzter Analyse", font=("Segoe UI", 14, "bold")).pack(side=LEFT)
        ttk.Button(top, text="Vorherige Inventur…", command=lambda: self._load("previous")).pack(side=LEFT, padx=(16, 4))
        ttk.Button(top, text="Aktuelle Inventur…", command=lambda: self._load("current")).pack(side=LEFT, padx=4)
        ttk.Button(top, text="Vergleichen", command=self.refresh).pack(side=LEFT, padx=4)

        self.kpi = ttk.Label(self, text="Noch kein Vergleich · 0 neue Funde")
        self.kpi.pack(fill=X, pady=(8, 8))

        cols = ("Projekt", "Art", "Chat", "Zeit", "Fund")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", height=18)
        widths = {"Projekt": 170, "Art": 145, "Chat": 220, "Zeit": 110, "Fund": 650}
        for c in cols:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=widths[c], anchor="w")
        self.tree.pack(fill=BOTH, expand=True)

        ttk.Label(
            self,
            text="Nur neue Funde werden angezeigt. Bereits bekannte Chat-Aussagen werden nicht doppelt gezählt.",
        ).pack(fill=X, pady=(8, 0))

    @staticmethod
    def _findings(payload: dict) -> list[dict]:
        if isinstance(payload.get("findings"), list):
            return payload["findings"]
        rows: list[dict] = []
        for conv in payload.get("conversations", []) or []:
            rows.extend(conv.get("findings", []) or [])
        if isinstance(payload.get("merged_findings"), list):
            rows.extend(payload["merged_findings"])
        return rows

    def _load(self, target: str):
        path = filedialog.askopenfilename(title="Inventur auswählen", filetypes=[("JSON", "*.json"), ("Alle Dateien", "*.*")])
        if not path:
            return
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
            rows = self._findings(payload)
        except Exception as exc:
            messagebox.showerror("Inventur", f"Datei konnte nicht gelesen werden:\n{exc}")
            return
        setattr(self, target, rows)
        self.kpi.config(text=f"{len(self.previous)} vorherige · {len(self.current)} aktuelle Funde geladen")
        if self.previous and self.current:
            self.refresh()

    def refresh(self):
        self.result = merge_findings(self.previous, self.current)
        for item in self.tree.get_children():
            self.tree.delete(item)
        for row in self.result.get("new_findings", []):
            text = " ".join(str(row.get("text") or "").split())
            self.tree.insert("", END, values=(
                row.get("project", ""), row.get("kind", ""), row.get("title", ""),
                row.get("timestamp", ""), text[:500],
            ))
        counts = self.result.get("counts", {})
        self.kpi.config(text=(
            f"{counts.get('previous', 0)} vorherige · {counts.get('merged', 0)} gesamt · "
            f"{counts.get('new', 0)} NEU seit letzter Analyse"
        ))
