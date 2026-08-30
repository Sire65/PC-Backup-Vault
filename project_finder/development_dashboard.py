from __future__ import annotations

import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .chat_inventory import inventory_export, save_inventory


class DevelopmentDashboard(tk.Toplevel):
    def __init__(self, master, *, get_development_summary):
        super().__init__(master)
        self.title("KC Entwicklungscenter")
        self.geometry("1180x720")
        self.minsize(900, 560)
        self.get_development_summary = get_development_summary
        self.chat_inventory = None
        self.status = tk.StringVar(value="Bereit")
        self._development_summary = {"counts": {}, "items": []}
        self._build()
        self.refresh()

    def _build(self):
        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")
        ttk.Button(top, text="↻ Aktualisieren", command=self.refresh).pack(side="left")
        ttk.Button(top, text="ChatGPT-Export inventarisieren", command=self.choose_chat_export).pack(side="left", padx=(8, 0))
        ttk.Button(top, text="Chat-Inventur speichern", command=self.save_chat_inventory).pack(side="left", padx=(8, 0))
        ttk.Label(top, textvariable=self.status).pack(side="right")

        self.summary = ttk.Label(self, padding=(10, 0), font=("Segoe UI", 11, "bold"))
        self.summary.pack(fill="x")

        cols = ("status", "projekt", "anforderung", "lokal", "github", "test", "grund")
        self.tree = ttk.Treeview(self, columns=cols, show="headings")
        labels = {
            "status": "Status", "projekt": "Projekt", "anforderung": "Anforderung / Fund",
            "lokal": "Lokal", "github": "GitHub", "test": "Test", "grund": "Bewertung",
        }
        widths = {"status": 70, "projekt": 180, "anforderung": 320, "lokal": 90, "github": 100, "test": 90, "grund": 330}
        for col in cols:
            self.tree.heading(col, text=labels[col])
            self.tree.column(col, width=widths[col], anchor="w", stretch=(col in {"anforderung", "grund"}))
        self.tree.pack(fill="both", expand=True, padx=10, pady=10)

    @staticmethod
    def _fmt_size(n: int) -> str:
        units = ["B", "KB", "MB", "GB", "TB"]
        x = float(n)
        for unit in units:
            if x < 1024 or unit == units[-1]:
                return f"{x:.1f} {unit}"
            x /= 1024
        return f"{x:.1f} TB"

    def choose_chat_export(self):
        path = filedialog.askopenfilename(
            title="ChatGPT-Datenexport auswählen",
            filetypes=[("ChatGPT Export", "*.zip *.json"), ("ZIP", "*.zip"), ("JSON", "*.json")],
        )
        if not path:
            return
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
            error_text = str(exc)
            self.after(0, lambda error_text=error_text: messagebox.showerror("Chat-Inventur", error_text))
            self.after(0, lambda: self.status.set("Fehler beim Chat-Import"))

    def save_chat_inventory(self):
        if not self.chat_inventory:
            messagebox.showinfo("Chat-Inventur", "Noch kein ChatGPT-Export analysiert.")
            return
        p = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON", "*.json")])
        if p:
            save_inventory(self.chat_inventory, p)
            self.status.set(f"Chat-Inventur gespeichert · {Path(p).name}")

    def refresh(self):
        self._development_summary = self.get_development_summary() or {"counts": {}, "items": []}
        counts = self._development_summary.get("counts", {})
        self.summary.configure(text=(
            f"Grün {counts.get('GREEN', 0)} · Gelb {counts.get('YELLOW', 0)} · "
            f"Rot {counts.get('RED', 0)} · Ungeprüft {counts.get('UNKNOWN', 0)}"
        ))
        self.tree.delete(*self.tree.get_children())
        icon = {"GREEN": "🟢", "YELLOW": "🟡", "RED": "🔴", "UNKNOWN": "⚪"}
        for item in self._development_summary.get("items", []):
            state = item.get("status", "UNKNOWN")
            self.tree.insert("", "end", values=(
                icon.get(state, "⚪"),
                item.get("project", ""),
                item.get("requirement", item.get("title", "")),
                item.get("local_state", ""),
                item.get("github_state", ""),
                item.get("test_state", ""),
                item.get("reason", ""),
            ))
