from __future__ import annotations

from tkinter import BOTH, END, LEFT, X, Canvas, StringVar, ttk

from .inventory_github_dashboard_model import build_inventory_github_dashboard


STATUS_SYMBOL = {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴"}


def _fmt_size(n: int) -> str:
    x = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if x < 1024 or unit == "TB":
            return f"{x:.1f} {unit}"
        x /= 1024
    return f"{x:.1f} TB"


class InventoryGitHubDashboard(ttk.Frame):
    """Graphical management view for Project Finder inventory and GitHub compare results."""

    def __init__(self, master, *, get_scan_items=None, get_github_report=None):
        super().__init__(master)
        self.get_scan_items = get_scan_items or (lambda: [])
        self.get_github_report = get_github_report or (lambda: None)
        keys = (
            "files", "data", "duplicates", "to_git", "git_review", "keep_local",
            "inventory_review", "quarantine", "github_compared", "github_identical",
            "github_local_only", "github_divergent", "github_ok", "repositories",
        )
        self.kpi = {key: StringVar(value="–") for key in keys}
        self.status = StringVar(value="Bereit · Inventur und GitHub-Vergleich sind read-only")
        self._build()
        self.refresh()

    def _build(self):
        head = ttk.Frame(self)
        head.pack(fill=X, padx=10, pady=(10, 5))
        ttk.Label(head, text="Inventur / GitHub Dashboard", font=("Segoe UI", 14, "bold")).pack(side=LEFT)
        ttk.Label(head, textvariable=self.status).pack(side="right")

        toolbar = ttk.Frame(self)
        toolbar.pack(fill=X, padx=10, pady=(0, 5))
        ttk.Button(toolbar, text="↻ Dashboard aktualisieren", command=self.refresh).pack(side=LEFT)
        ttk.Label(
            toolbar,
            text="Zeigt ausschließlich bereits erfasste Inventur- und GitHub-Vergleichsdaten; keine automatische Git-Schreibaktion.",
        ).pack(side=LEFT, padx=12)

        cards = ttk.Frame(self)
        cards.pack(fill=X, padx=10, pady=4)
        specs = [
            ("Dateien", "files"), ("Datenmenge", "data"), ("Dubletten", "duplicates"), ("Zu Git", "to_git"),
            ("Git prüfen", "git_review"), ("Lokal behalten", "keep_local"), ("Inventur prüfen", "inventory_review"), ("Quarantäne-Kandidaten", "quarantine"),
            ("GitHub geprüft", "github_compared"), ("GitHub identisch", "github_identical"), ("Nur lokal", "github_local_only"), ("Abweichend", "github_divergent"),
            ("GitHub OK", "github_ok"), ("Repositories", "repositories"),
        ]
        for idx, (title, key) in enumerate(specs):
            box = ttk.LabelFrame(cards, text=title)
            box.grid(row=idx // 4, column=idx % 4, sticky="nsew", padx=3, pady=3)
            ttk.Label(box, textvariable=self.kpi[key], font=("Segoe UI", 12, "bold")).pack(padx=12, pady=8)
        for c in range(4):
            cards.columnconfigure(c, weight=1)

        charts = ttk.Frame(self)
        charts.pack(fill=X, padx=10, pady=5)
        self.inventory_canvas = Canvas(charts, height=175, highlightthickness=0)
        self.inventory_canvas.pack(side=LEFT, fill=BOTH, expand=True, padx=(0, 5))
        self.github_canvas = Canvas(charts, height=175, highlightthickness=0)
        self.github_canvas.pack(side=LEFT, fill=BOTH, expand=True, padx=(5, 0))

        tablebox = ttk.LabelFrame(self, text="GitHub-Repositories / Übergabestatus")
        tablebox.pack(fill=BOTH, expand=True, padx=10, pady=(4, 10))
        cols = ("status", "repo", "total", "identical", "local_only", "divergent", "possible", "unavailable", "unassigned")
        labels = {
            "status": "Ampel", "repo": "Repository", "total": "Geprüft", "identical": "Identisch",
            "local_only": "Nur lokal", "divergent": "Abweichend", "possible": "Wahrscheinlich",
            "unavailable": "Nicht erreichbar", "unassigned": "Unzugeordnet",
        }
        widths = {"status": 60, "repo": 285, "total": 70, "identical": 75, "local_only": 75, "divergent": 80, "possible": 90, "unavailable": 95, "unassigned": 90}
        self.tree = ttk.Treeview(tablebox, columns=cols, show="headings", height=12)
        for col in cols:
            self.tree.heading(col, text=labels[col])
            self.tree.column(col, width=widths[col], anchor="w" if col == "repo" else "center")
        self.tree.pack(fill=BOTH, expand=True, padx=6, pady=6)

    def refresh(self):
        model = build_inventory_github_dashboard(self.get_scan_items(), self.get_github_report())
        k = model["kpi"]
        values = {
            "files": f"{k['files']:,}",
            "data": _fmt_size(k["bytes"]),
            "duplicates": f"{k['duplicates']:,} · {_fmt_size(k['duplicate_bytes'])}",
            "to_git": f"{k['to_git']:,}",
            "git_review": f"{k['git_review']:,}",
            "keep_local": f"{k['keep_local']:,}",
            "inventory_review": f"{k['inventory_review']:,}",
            "quarantine": f"{k['quarantine_candidates']:,}",
            "github_compared": f"{k['github_compared']:,}",
            "github_identical": f"{k['github_identical']:,}",
            "github_local_only": f"{k['github_local_only']:,}",
            "github_divergent": f"{k['github_divergent']:,}",
            "github_ok": f"{k['github_ok_percent']:.1f} %",
            "repositories": f"{k['repositories']:,}",
        }
        for key, value in values.items():
            self.kpi[key].set(value)

        self.tree.delete(*self.tree.get_children())
        for row in model["repositories"]:
            self.tree.insert("", END, values=(
                STATUS_SYMBOL.get(row["status"], "🟡"), row["repo"], row["total"], row["identical"],
                row["local_only"], row["divergent"], row["possible"], row["unavailable"], row["unassigned"],
            ))

        self._draw_bars(
            self.inventory_canvas,
            "Inventurentscheidungen",
            {
                "Zu Git": k["to_git"], "Git prüfen": k["git_review"], "Lokal": k["keep_local"],
                "Prüfen": k["inventory_review"], "Quarantäne": k["quarantine_candidates"],
            },
        )
        self._draw_bars(
            self.github_canvas,
            "GitHub-Vergleich",
            {
                "Identisch": k["github_identical"], "Nur lokal": k["github_local_only"],
                "Abweichend": k["github_divergent"], "Möglich": k["github_possible"],
                "Nicht erreichbar": k["github_unavailable"],
            },
        )
        if not k["files"]:
            self.status.set("Noch keine Inventur geladen · zuerst Festplatten-Analyse starten")
        elif not k["github_compared"]:
            self.status.set("Inventur geladen · GitHub-Vergleich noch nicht durchgeführt")
        else:
            self.status.set(
                f"Aktuell · {k['files']:,} Dateien · {k['repositories']:,} Repositories · GitHub identisch {k['github_ok_percent']:.1f} %"
            )

    @staticmethod
    def _draw_bars(canvas: Canvas, title: str, values: dict[str, int]):
        canvas.delete("all")
        canvas.update_idletasks()
        w = max(canvas.winfo_width(), 480)
        h = max(canvas.winfo_height(), 175)
        canvas.create_text(8, 10, anchor="nw", text=title, font=("Segoe UI", 10, "bold"))
        keys = list(values)
        vals = [int(values[k] or 0) for k in keys]
        maxv = max(max(vals, default=0), 1)
        top, bottom = 38, h - 32
        gap = 12
        barw = max(34, (w - 30 - gap * max(0, len(keys) - 1)) // max(1, len(keys)))
        for i, (key, val) in enumerate(zip(keys, vals)):
            x0 = 15 + i * (barw + gap)
            x1 = min(w - 8, x0 + barw)
            y1 = bottom
            y0 = bottom - ((bottom - top) * val / maxv)
            canvas.create_rectangle(x0, y0, x1, y1, outline="#777", fill="#d9d9d9")
            canvas.create_text((x0 + x1) / 2, y0 - 8, text=str(val), font=("Segoe UI", 8))
            canvas.create_text((x0 + x1) / 2, bottom + 12, text=key[:14], font=("Segoe UI", 7))
