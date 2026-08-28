from __future__ import annotations

from tkinter import BOTH, END, LEFT, X, Canvas, filedialog, messagebox, ttk
import json
from pathlib import Path

from .change_dashboard_model import summarize_changes
from .incremental_chat_merge import merge_findings


class ChangesSinceLastTab(ttk.Frame):
    """Shows newly discovered development evidence between two local inventories."""

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
        self.kpi.pack(fill=X, pady=(8, 5))

        cards = ttk.Frame(self)
        cards.pack(fill=X, pady=(0, 6))
        self.card_vars = {}
        for key, label in (("new", "Neue Funde"), ("projects_affected", "Projekte"),
                           ("open_or_error", "Offen/Fehler"), ("implementation_claims", "Umsetzung behauptet"),
                           ("ideas", "Neue Ideen")):
            box = ttk.LabelFrame(cards, text=label, padding=(10, 5))
            box.pack(side=LEFT, fill=X, expand=True, padx=(0, 5))
            var = self.card_vars[key] = __import__("tkinter").StringVar(value="0")
            ttk.Label(box, textvariable=var, font=("Segoe UI", 15, "bold")).pack()

        self.chart = Canvas(self, height=90, highlightthickness=0)
        self.chart.pack(fill=X, pady=(0, 7))
        self.chart.bind("<Configure>", lambda _e: self._draw_chart())

        cols = ("Projekt", "Art", "Chat", "Zeit", "Fund")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", height=15)
        widths = {"Projekt": 170, "Art": 145, "Chat": 220, "Zeit": 110, "Fund": 650}
        for c in cols:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=widths[c], anchor="w")
        self.tree.pack(fill=BOTH, expand=True)

        ttk.Label(self, text="Nur echte neue Funde. Bereits bekannte Chat-Aussagen werden nicht doppelt gezählt.").pack(fill=X, pady=(8, 0))

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
        new_rows = self.result.get("new_findings", [])
        summary = summarize_changes(new_rows)
        for key, var in self.card_vars.items():
            var.set(str(summary["counts"].get(key, 0)))
        self._change_summary = summary
        self._draw_chart()
        for item in self.tree.get_children():
            self.tree.delete(item)
        ordered = sorted(new_rows, key=lambda x: (x.get("kind") != "OPEN_OR_ERROR", str(x.get("project") or "")))
        for row in ordered:
            text = " ".join(str(row.get("text") or "").split())
            self.tree.insert("", END, values=(row.get("project", ""), row.get("kind", ""), row.get("title", ""), row.get("timestamp", ""), text[:500]))
        counts = self.result.get("counts", {})
        self.kpi.config(text=f"{counts.get('previous', 0)} vorherige · {counts.get('merged', 0)} gesamt · {counts.get('new', 0)} NEU seit letzter Analyse")

    def _draw_chart(self):
        self.chart.delete("all")
        summary = getattr(self, "_change_summary", {"projects": {}})
        rows = list(summary.get("projects", {}).items())[:8]
        if not rows:
            self.chart.create_text(12, 42, anchor="w", text="Noch keine Änderungsdaten für die Grafik.")
            return
        width = max(300, self.chart.winfo_width())
        maximum = max(v for _, v in rows) or 1
        y = 8
        for project, value in rows:
            self.chart.create_text(8, y + 8, anchor="w", text=str(project)[:24])
            x0 = 170
            x1 = x0 + int((width - 230) * value / maximum)
            self.chart.create_rectangle(x0, y + 2, x1, y + 15, outline="")
            self.chart.create_text(x1 + 8, y + 8, anchor="w", text=str(value))
            y += 20
