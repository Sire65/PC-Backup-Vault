from __future__ import annotations

import threading
from tkinter import BOTH, END, LEFT, X, Canvas, StringVar, ttk


class CoreJobsDashboard(ttk.Frame):
    """Combined management view over backup_vault.unified_jobs.

    The view is read-only. If Core/Neon is unavailable, the rest of Project Finder keeps working.
    """

    def __init__(self, master):
        super().__init__(master)
        self.status = StringVar(value="Bereit · zentrale Jobs werden nur gelesen")
        self.kpi = {k: StringVar(value="–") for k in (
            "runs", "success", "failed", "warnings", "errors", "success_percent",
            "backup", "inventory", "github", "items", "data",
        )}
        self._build()

    def _build(self):
        head = ttk.Frame(self)
        head.pack(fill=X, padx=10, pady=(10, 5))
        ttk.Label(head, text="Zentrale Jobs · Backup / Inventur / GitHub", font=("Segoe UI", 14, "bold")).pack(side=LEFT)
        ttk.Label(head, textvariable=self.status).pack(side="right")

        toolbar = ttk.Frame(self)
        toolbar.pack(fill=X, padx=10, pady=(0, 5))
        ttk.Button(toolbar, text="↻ Core aktualisieren", command=self.refresh).pack(side=LEFT)
        ttk.Label(toolbar, text="Read-only Gesamtansicht; Ausfall von Core/Neon blockiert weder Backup noch Inventur.").pack(side=LEFT, padx=12)

        cards = ttk.Frame(self)
        cards.pack(fill=X, padx=10, pady=4)
        specs = [
            ("Jobs gesamt", "runs"), ("Erfolgreich", "success"), ("Fehlgeschlagen", "failed"), ("Erfolgsquote", "success_percent"),
            ("Warnungen", "warnings"), ("Fehler", "errors"), ("Backup", "backup"), ("Inventur", "inventory"),
            ("GitHub", "github"), ("Objekte/Dateien", "items"), ("Datenmenge", "data"),
        ]
        for idx, (title, key) in enumerate(specs):
            box = ttk.LabelFrame(cards, text=title)
            box.grid(row=idx // 4, column=idx % 4, sticky="nsew", padx=3, pady=3)
            ttk.Label(box, textvariable=self.kpi[key], font=("Segoe UI", 12, "bold")).pack(padx=12, pady=8)
        for col in range(4):
            cards.columnconfigure(col, weight=1)

        self.canvas = Canvas(self, height=155, highlightthickness=0)
        self.canvas.pack(fill=X, padx=10, pady=5)

        box = ttk.LabelFrame(self, text="Gemeinsames Job-Protokoll")
        box.pack(fill=BOTH, expand=True, padx=10, pady=(4, 10))
        cols = ("time", "program", "type", "status", "items", "data", "warnings", "errors", "duration", "summary")
        labels = {
            "time": "Start", "program": "Programm", "type": "Job", "status": "Status", "items": "Anzahl",
            "data": "Daten", "warnings": "Warn.", "errors": "Fehler", "duration": "Dauer", "summary": "Zusammenfassung",
        }
        widths = {"time": 145, "program": 150, "type": 125, "status": 90, "items": 80, "data": 90, "warnings": 60, "errors": 60, "duration": 80, "summary": 420}
        self.tree = ttk.Treeview(box, columns=cols, show="headings", height=14)
        for col in cols:
            self.tree.heading(col, text=labels[col])
            self.tree.column(col, width=widths[col], anchor="w" if col in {"program", "summary"} else "center")
        self.tree.pack(fill=BOTH, expand=True, padx=6, pady=6)

    def refresh(self):
        self.status.set("Core wird gelesen…")
        threading.Thread(target=self._load_worker, daemon=True).start()

    def _load_worker(self):
        try:
            from config_store import ConfigStore
            from vault_db import recent_unified_jobs, unified_job_kpis

            store = ConfigStore()
            profile = store.get_profile()
            if not profile:
                self.after(0, lambda: self._show_error("Kein aktives Speicherprofil"))
                return
            dsn = store.get_dsn(profile.get("id"))
            if not dsn:
                self.after(0, lambda: self._show_error("Core nicht verbunden · DSN fehlt"))
                return
            rows = recent_unified_jobs(dsn, 1000)
            kpis = unified_job_kpis(rows)
            if not rows:
                self.after(0, lambda: self._show_error("Core-Jobs noch nicht verfügbar · ggf. Core/Schema aktualisieren"))
                return
            self.after(0, lambda: self._render(rows, kpis))
        except Exception as exc:
            text = str(exc)
            self.after(0, lambda: self._show_error(f"Core nicht verfügbar · {text[:160]}"))

    def _render(self, rows: list[dict], k: dict):
        by_type = k.get("by_type") or {}
        values = {
            "runs": f"{k['runs']:,}", "success": f"{k['success']:,}", "failed": f"{k['failed']:,}",
            "success_percent": f"{k['success_percent']:.1f} %", "warnings": f"{k['warnings']:,}", "errors": f"{k['errors']:,}",
            "backup": f"{int(by_type.get('BACKUP', 0)):,}", "inventory": f"{int(by_type.get('INVENTORY', 0)):,}",
            "github": f"{int(by_type.get('GITHUB_COMPARE', 0)):,}", "items": f"{k['items']:,}", "data": self._fmt_size(k['bytes']),
        }
        for key, value in values.items():
            self.kpi[key].set(value)

        self.tree.delete(*self.tree.get_children())
        for row in rows[:500]:
            started = row.get("started_at")
            started_text = started.strftime("%d.%m.%Y %H:%M:%S") if hasattr(started, "strftime") else str(started or "")[:19]
            self.tree.insert("", END, values=(
                started_text, row.get("program_name") or "", row.get("job_type") or "", row.get("status") or "",
                f"{int(row.get('item_count') or 0):,}", self._fmt_size(int(row.get("byte_count") or 0)),
                int(row.get("warning_count") or 0), int(row.get("error_count") or 0),
                f"{float(row.get('duration_seconds') or 0):.1f} s", row.get("summary") or "",
            ))
        self._draw_type_bars(by_type)
        self.status.set(f"Core aktuell · {k['runs']:,} Jobs · Erfolgsquote {k['success_percent']:.1f} %")

    def _show_error(self, text: str):
        self.status.set(text)
        for var in self.kpi.values():
            var.set("–")
        self.tree.delete(*self.tree.get_children())
        self.canvas.delete("all")
        self.canvas.create_text(10, 18, anchor="nw", text=text)

    def _draw_type_bars(self, by_type: dict):
        self.canvas.delete("all")
        self.canvas.update_idletasks()
        values = [("Backup", int(by_type.get("BACKUP", 0))), ("Inventur", int(by_type.get("INVENTORY", 0))), ("GitHub", int(by_type.get("GITHUB_COMPARE", 0))), ("Verify", int(by_type.get("VERIFY", 0))), ("Restore", int(by_type.get("RESTORE_TEST", 0))), ("Update", int(by_type.get("UPDATE_INSTALL", 0)) + int(by_type.get("UPDATE_CHECK", 0)))]
        w = max(self.canvas.winfo_width(), 700)
        h = max(self.canvas.winfo_height(), 155)
        self.canvas.create_text(8, 8, anchor="nw", text="Jobs nach Typ", font=("Segoe UI", 10, "bold"))
        maxv = max([v for _, v in values] + [1])
        bottom, top, gap = h - 28, 36, 14
        barw = max(48, (w - 40 - gap * (len(values) - 1)) // len(values))
        for idx, (label, value) in enumerate(values):
            x0 = 15 + idx * (barw + gap); x1 = x0 + barw
            y1 = bottom; y0 = bottom - ((bottom - top) * value / maxv)
            self.canvas.create_rectangle(x0, y0, x1, y1, outline="#777", fill="#d9d9d9")
            self.canvas.create_text((x0+x1)/2, y0-8, text=str(value), font=("Segoe UI", 8))
            self.canvas.create_text((x0+x1)/2, bottom+11, text=label, font=("Segoe UI", 8))

    @staticmethod
    def _fmt_size(n: int) -> str:
        value = float(n or 0)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if value < 1024 or unit == "TB":
                return f"{value:.1f} {unit}"
            value /= 1024
        return f"{value:.1f} TB"
