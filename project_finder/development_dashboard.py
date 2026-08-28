from __future__ import annotations

import json
import threading
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, X, Canvas, StringVar, filedialog, messagebox, ttk

from .chat_inventory import inventory_export, save_inventory
from .dashboard_model import build_dashboard


class DevelopmentDashboard(ttk.Frame):
    """Compact dashboard for file/chat/development inventory.

    It consumes real scan/chat/evidence results only. No simulated production data is shown.
    """

    def __init__(self, master, *, get_scan_items=None, get_development_summary=None):
        super().__init__(master)
        self.get_scan_items = get_scan_items or (lambda: [])
        self.get_development_summary = get_development_summary or (lambda: {"counts": {}, "items": []})
        self.chat_inventory: dict = {}
        self.status = StringVar(value="Bereit · Noch kein ChatGPT-Export eingelesen")
        self.kpi_vars = {k: StringVar(value="–") for k in (
            "files", "data", "projects", "chats", "findings", "proven", "open", "duplicates"
        )}
        self._build()
        self.refresh()

    def _build(self):
        head = ttk.Frame(self); head.pack(fill=X, padx=10, pady=(10, 5))
        ttk.Label(head, text="Entwicklungszentrale", font=("Segoe UI", 14, "bold")).pack(side=LEFT)
        ttk.Label(head, textvariable=self.status).pack(side=RIGHT)

        toolbar = ttk.Frame(self); toolbar.pack(fill=X, padx=10, pady=5)
        ttk.Button(toolbar, text="ChatGPT-Export einlesen…", command=self.choose_chat_export).pack(side=LEFT, padx=(0, 6))
        ttk.Button(toolbar, text="Dashboard aktualisieren", command=self.refresh).pack(side=LEFT, padx=(0, 6))
        ttk.Button(toolbar, text="Chat-Inventur speichern…", command=self.save_chat_inventory).pack(side=LEFT)

        kpis = ttk.Frame(self); kpis.pack(fill=X, padx=10, pady=(2, 6))
        specs = [
            ("Dateien", "files"), ("Datenmenge", "data"), ("Projekte", "projects"), ("Entwicklungs-Chats", "chats"),
            ("Chat-Funde", "findings"), ("Nachgewiesen", "proven"), ("Offen/verloren", "open"), ("Dubletten", "duplicates"),
        ]
        for idx, (title, key) in enumerate(specs):
            box = ttk.LabelFrame(kpis, text=title)
            box.grid(row=idx // 4, column=idx % 4, sticky="nsew", padx=3, pady=3)
            ttk.Label(box, textvariable=self.kpi_vars[key], font=("Segoe UI", 12, "bold")).pack(padx=12, pady=8)
        for c in range(4): kpis.columnconfigure(c, weight=1)

        middle = ttk.Frame(self); middle.pack(fill=X, padx=10, pady=4)
        self.dev_canvas = Canvas(middle, height=150, highlightthickness=0)
        self.dev_canvas.pack(side=LEFT, fill=BOTH, expand=True, padx=(0, 5))
        self.file_canvas = Canvas(middle, height=150, highlightthickness=0)
        self.file_canvas.pack(side=LEFT, fill=BOTH, expand=True, padx=(5, 0))

        tablebox = ttk.LabelFrame(self, text="Projektübersicht · zuerst die wichtigsten offenen Punkte")
        tablebox.pack(fill=BOTH, expand=True, padx=10, pady=(4, 10))
        cols = ("project", "findings", "ideas", "claims", "open", "green", "yellow", "red")
        self.tree = ttk.Treeview(tablebox, columns=cols, show="headings", height=12)
        labels = {
            "project": "Projekt", "findings": "Chat-Funde", "ideas": "Ideen", "claims": "Umsetzung behauptet",
            "open": "Chat offen/Fehler", "green": "🟢 belegt", "yellow": "🟡 prüfen", "red": "🔴 offen/verloren",
        }
        widths = {"project": 240, "findings": 90, "ideas": 70, "claims": 135, "open": 115, "green": 80, "yellow": 80, "red": 110}
        for c in cols:
            self.tree.heading(c, text=labels[c]); self.tree.column(c, width=widths[c], anchor="w" if c == "project" else "center")
        self.tree.pack(fill=BOTH, expand=True, padx=6, pady=6)

    @staticmethod
    def _fmt_size(n: int) -> str:
        x = float(n)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if x < 1024 or unit == "TB": return f"{x:.1f} {unit}"
            x /= 1024
        return f"{x:.1f} TB"

    def choose_chat_export(self):
        path = filedialog.askopenfilename(
            title="ChatGPT-Datenexport auswählen",
            filetypes=[("ChatGPT Export", "*.zip *.json"), ("ZIP", "*.zip"), ("JSON", "*.json")],
        )
        if not path: return
        self.status.set("ChatGPT-Export wird lokal analysiert…")
        threading.Thread(target=self._load_chat_worker, args=(path,), daemon=True).start()

    def _load_chat_worker(self, path: str):
        try:
            inv = inventory_export(path, include_other=False)
            self.chat_inventory = inv
            self.after(0, self.refresh)
            self.after(0, lambda: self.status.set(
                f"Chat-Inventur fertig · {inv.get('conversation_count', 0):,} Chats · {inv.get('selected_count', 0):,} entwicklungsrelevant"
            ))
        except Exception as exc:
            self.after(0, lambda: messagebox.showerror("Chat-Inventur", str(exc)))
            self.after(0, lambda: self.status.set("Fehler beim Chat-Import"))

    def save_chat_inventory(self):
        if not self.chat_inventory:
            messagebox.showinfo("Chat-Inventur", "Noch kein ChatGPT-Export analysiert."); return
        p = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")])
        if p:
            save_inventory(self.chat_inventory, p)
            self.status.set(f"Chat-Inventur gespeichert · {Path(p).name}")

    def refresh(self):
        model = build_dashboard(
            scan_items=self.get_scan_items(),
            chat_inventory=self.chat_inventory,
            development_summary=self.get_development_summary(),
        )
        k = model["kpi"]
        values = {
            "files": f"{k['files']:,}", "data": self._fmt_size(k["bytes"]), "projects": f"{k['projects']:,}",
            "chats": f"{k['chats_development']:,} + {k['chats_possible']:,}?", "findings": f"{k['chat_findings']:,}",
            "proven": f"{k['proven_percent']:.1f}%", "open": f"{k['open_or_lost']:,}",
            "duplicates": f"{k['duplicates']:,} · {self._fmt_size(k['duplicate_bytes'])}",
        }
        for key, value in values.items(): self.kpi_vars[key].set(value)

        self.tree.delete(*self.tree.get_children())
        for r in model["projects"]:
            self.tree.insert("", END, values=(r["project"], r["chat_findings"], r["ideas"], r["claims"], r["open"], r["green"], r["yellow"], r["red"]))
        self._draw_bars(self.dev_canvas, "Entwicklungsstand", model["development"], ["GREEN", "YELLOW", "RED", "BLUE"])
        self._draw_bars(self.file_canvas, "Dateitypen", model["file_categories"], list(model["file_categories"].keys())[:6])

    @staticmethod
    def _draw_bars(canvas: Canvas, title: str, values: dict, keys: list[str]):
        canvas.delete("all")
        canvas.update_idletasks()
        w = max(canvas.winfo_width(), 360); h = max(canvas.winfo_height(), 150)
        canvas.create_text(8, 10, anchor="nw", text=title, font=("Segoe UI", 10, "bold"))
        vals = [int(values.get(k, 0) or 0) for k in keys]
        maxv = max(vals) if vals else 1
        maxv = max(maxv, 1)
        top, bottom = 34, h - 26
        barw = max(28, (w - 30) // max(len(keys), 1) - 12)
        for i, (key, val) in enumerate(zip(keys, vals)):
            x0 = 15 + i * (barw + 12); x1 = x0 + barw
            y1 = bottom; y0 = bottom - ((bottom - top) * val / maxv)
            canvas.create_rectangle(x0, y0, x1, y1, outline="#777", fill="#d9d9d9")
            canvas.create_text((x0+x1)/2, y0-8, text=str(val), font=("Segoe UI", 8))
            canvas.create_text((x0+x1)/2, bottom+11, text=str(key)[:10], font=("Segoe UI", 7))
