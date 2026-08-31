from __future__ import annotations

from collections import Counter
from tkinter import BOTH, END, LEFT, X, Canvas, StringVar, ttk

from .inventory_job_history import history_kpis, read_jobs


def _fmt_size(n: int) -> str:
    x = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if x < 1024 or unit == "TB":
            return f"{x:.1f} {unit}"
        x /= 1024
    return f"{x:.1f} TB"


class InventoryHistoryDashboard(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        keys = ("runs", "inventory", "github", "success", "failed", "cancelled", "success_pct", "files", "data", "to_git", "divergent", "unavailable")
        self.kpi = {k: StringVar(value="–") for k in keys}
        self.status = StringVar(value="Noch keine Historie geladen")
        self._build()
        self.refresh()

    def _build(self):
        head = ttk.Frame(self); head.pack(fill=X, padx=10, pady=(10, 5))
        ttk.Label(head, text="Inventur / GitHub Verlauf", font=("Segoe UI", 14, "bold")).pack(side=LEFT)
        ttk.Label(head, textvariable=self.status).pack(side="right")
        bar = ttk.Frame(self); bar.pack(fill=X, padx=10, pady=(0, 5))
        ttk.Button(bar, text="↻ Verlauf aktualisieren", command=self.refresh).pack(side=LEFT)
        ttk.Label(bar, text="Append-only Protokoll · nur Kennzahlen/Status · keine Backupdaten oder Secrets").pack(side=LEFT, padx=12)

        cards = ttk.Frame(self); cards.pack(fill=X, padx=10, pady=4)
        specs = [
            ("Läufe", "runs"), ("Inventuren", "inventory"), ("GitHub-Vergleiche", "github"), ("Erfolgreich", "success"),
            ("Fehler", "failed"), ("Abgebrochen", "cancelled"), ("Erfolgsquote", "success_pct"), ("Dateien gescannt", "files"),
            ("Daten gescannt", "data"), ("Zu Git erkannt", "to_git"), ("Abweichungen", "divergent"), ("Repo-Fehler", "unavailable"),
        ]
        for idx, (title, key) in enumerate(specs):
            box = ttk.LabelFrame(cards, text=title); box.grid(row=idx // 4, column=idx % 4, sticky="nsew", padx=3, pady=3)
            ttk.Label(box, textvariable=self.kpi[key], font=("Segoe UI", 12, "bold")).pack(padx=12, pady=8)
        for c in range(4): cards.columnconfigure(c, weight=1)

        charts = ttk.Frame(self); charts.pack(fill=X, padx=10, pady=5)
        self.status_canvas = Canvas(charts, height=160, highlightthickness=0); self.status_canvas.pack(side=LEFT, fill=BOTH, expand=True, padx=(0,5))
        self.type_canvas = Canvas(charts, height=160, highlightthickness=0); self.type_canvas.pack(side=LEFT, fill=BOTH, expand=True, padx=(5,0))

        box = ttk.LabelFrame(self, text="Protokoll der letzten Inventur- und GitHub-Jobs")
        box.pack(fill=BOTH, expand=True, padx=10, pady=(4,10))
        cols = ("when", "type", "status", "duration", "files", "to_git", "identical", "local_only", "divergent", "error")
        labels = {"when":"Zeit", "type":"Job", "status":"Status", "duration":"Dauer", "files":"Dateien", "to_git":"Zu Git", "identical":"Identisch", "local_only":"Nur lokal", "divergent":"Abweichend", "error":"Repo-Fehler"}
        widths = {"when":155,"type":130,"status":90,"duration":80,"files":85,"to_git":70,"identical":75,"local_only":75,"divergent":80,"error":80}
        self.tree = ttk.Treeview(box, columns=cols, show="headings", height=13)
        for c in cols:
            self.tree.heading(c, text=labels[c]); self.tree.column(c, width=widths[c], anchor="center")
        self.tree.pack(fill=BOTH, expand=True, padx=6, pady=6)

    def refresh(self):
        rows = read_jobs(limit=1000)
        k = history_kpis(rows)
        vals = {
            "runs": f"{k['runs']:,}", "inventory": f"{k['inventory_runs']:,}", "github": f"{k['github_runs']:,}",
            "success": f"{k['success']:,}", "failed": f"{k['failed']:,}", "cancelled": f"{k['cancelled']:,}",
            "success_pct": f"{k['success_percent']:.1f} %", "files": f"{k['files_scanned']:,}", "data": _fmt_size(k['bytes_scanned']),
            "to_git": f"{k['to_git']:,}", "divergent": f"{k['github_divergent']:,}", "unavailable": f"{k['github_unavailable']:,}",
        }
        for key, value in vals.items(): self.kpi[key].set(value)
        self.tree.delete(*self.tree.get_children())
        for row in rows[:250]:
            self.tree.insert("", END, values=(
                row.get("finished_at") or row.get("recorded_at") or "", row.get("job_type", ""), row.get("status", ""),
                f"{float(row.get('duration_seconds') or 0):.1f}s", int(row.get("files") or 0), int(row.get("to_git") or 0),
                int(row.get("identical") or 0), int(row.get("local_only") or 0), int(row.get("divergent") or 0), int(row.get("unavailable") or 0),
            ))
        self._draw(self.status_canvas, "Job-Ergebnisse", Counter(str(x.get("status") or "UNKNOWN") for x in rows))
        self._draw(self.type_canvas, "Job-Arten", Counter(str(x.get("job_type") or "UNKNOWN") for x in rows))
        self.status.set(f"{k['runs']:,} protokollierte Läufe · Erfolgsquote {k['success_percent']:.1f} %")

    @staticmethod
    def _draw(canvas: Canvas, title: str, values):
        canvas.delete("all"); canvas.update_idletasks()
        w=max(canvas.winfo_width(),420); h=max(canvas.winfo_height(),160)
        canvas.create_text(8,10,anchor="nw",text=title,font=("Segoe UI",10,"bold"))
        items=list(values.items())[:6]; maxv=max([int(v) for _,v in items] or [1])
        top,bottom=36,h-30; gap=12; barw=max(36,(w-30-gap*max(0,len(items)-1))//max(1,len(items)))
        for i,(key,val) in enumerate(items):
            val=int(val); x0=15+i*(barw+gap); x1=min(w-8,x0+barw); y1=bottom; y0=bottom-((bottom-top)*val/maxv)
            canvas.create_rectangle(x0,y0,x1,y1,outline="#777",fill="#d9d9d9")
            canvas.create_text((x0+x1)/2,y0-8,text=str(val),font=("Segoe UI",8)); canvas.create_text((x0+x1)/2,bottom+12,text=str(key)[:14],font=("Segoe UI",7))
