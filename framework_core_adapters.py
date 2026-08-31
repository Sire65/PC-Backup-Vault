from __future__ import annotations

"""Tkinter adapters governed by Framework Studio core contracts.

These are deliberately *adapters*, not replacement cores. Framework Studio remains
source of truth for DesignCore, WindowCore, TableCore and NavigationCore semantics.
PC Backup Vault uses Tkinter, while the reference runtime is JavaScript/CSS, so this
module maps the approved contracts to native Tk widgets without forking product logic.
"""

from dataclasses import dataclass
import tkinter as tk
from tkinter import ttk


FRAMEWORK_PROVENANCE = {
    "source_package": "FrameworkStudio_1_38_38 / candidate 1.38.39",
    "design_core": "master.design / DesignCore V1.0",
    "window_core": "master.window / WindowCore API v1",
    "table_core": "TableCore V1.0",
    "navigation_core": "NavigationCore V1.0",
    "governance": "Framework Studio 2.0.1 Training/Governance Candidate",
}


@dataclass(frozen=True)
class DesignTokens:
    font_family: str = "Segoe UI"
    bg: str = "#f1f5f9"
    surface: str = "#ffffff"
    surface_soft: str = "#f8fafc"
    text: str = "#0f172a"
    muted: str = "#64748b"
    border: str = "#dbe3ee"
    primary: str = "#1d4ed8"
    ok: str = "#16a34a"
    warn: str = "#d97706"
    error: str = "#dc2626"
    off: str = "#94a3b8"
    radius_hint: int = 8
    gap: int = 10


TOKENS = DesignTokens()


def apply_design_adapter(root: tk.Misc) -> None:
    """Apply common DesignCore-derived tokens to ttk without product semantics."""
    style = ttk.Style(root)
    try:
        if "vista" in style.theme_names():
            style.theme_use("vista")
    except Exception:
        pass
    style.configure("Vault.TFrame", background=TOKENS.bg)
    style.configure("Surface.TFrame", background=TOKENS.surface)
    style.configure("Vault.TLabel", font=(TOKENS.font_family, 9), foreground=TOKENS.text)
    style.configure("Muted.TLabel", font=(TOKENS.font_family, 9), foreground=TOKENS.muted)
    style.configure("Title.TLabel", font=(TOKENS.font_family, 20, "bold"), foreground=TOKENS.text)
    style.configure("Section.TLabel", font=(TOKENS.font_family, 11, "bold"), foreground=TOKENS.text)
    style.configure("Module.TButton", font=(TOKENS.font_family, 10, "bold"), padding=(12, 10))
    style.configure("Vault.Treeview", rowheight=28, font=(TOKENS.font_family, 9))
    style.configure("Vault.Treeview.Heading", font=(TOKENS.font_family, 9, "bold"))


def normalize_window_geometry(window: tk.Toplevel | tk.Tk, width: int, height: int,
                              min_width: int = 900, min_height: int = 600) -> None:
    """WindowCore adapter: validate viewport, keep the window on-screen and centered."""
    window.update_idletasks()
    sw = max(800, int(window.winfo_screenwidth()))
    sh = max(600, int(window.winfo_screenheight()))
    width = min(max(min_width, width), max(min_width, sw - 40))
    height = min(max(min_height, height), max(min_height, sh - 80))
    x = max(0, (sw - width) // 2)
    y = max(0, (sh - height) // 2)
    window.geometry(f"{width}x{height}+{x}+{y}")
    window.minsize(min(min_width, sw), min(min_height, sh))


def bind_window_escape(window: tk.Toplevel, close_command=None) -> None:
    """WindowCore rule: Escape affects only the topmost closable context."""
    command = close_command or window.destroy
    window.bind("<Escape>", lambda _e: command())


def configure_table(tree: ttk.Treeview, columns: list[tuple[str, str, int, str]],
                    sortable: bool = True) -> None:
    """TableCore adapter for consistent headings, widths, alignment and sorting."""
    tree.configure(columns=tuple(c[0] for c in columns), show="headings", style="Vault.Treeview")

    def sort_column(col: str, descending: bool = False):
        rows = [(tree.set(iid, col), iid) for iid in tree.get_children("")]
        def key(v):
            raw = (v[0] or "").strip().replace("%", "").replace(",", ".")
            try:
                return (0, float(raw))
            except Exception:
                return (1, raw.casefold())
        rows.sort(key=key, reverse=descending)
        for idx, (_, iid) in enumerate(rows):
            tree.move(iid, "", idx)
        tree.heading(col, command=lambda: sort_column(col, not descending))

    for col, title, width, anchor in columns:
        tree.heading(col, text=title)
        tree.column(col, width=width, minwidth=60, anchor=anchor, stretch=True)
        if sortable:
            tree.heading(col, command=lambda c=col: sort_column(c, False))


def status_color(level: str) -> str:
    return {
        "ok": TOKENS.ok,
        "green": TOKENS.ok,
        "warn": TOKENS.warn,
        "yellow": TOKENS.warn,
        "error": TOKENS.error,
        "red": TOKENS.error,
        "off": TOKENS.off,
        "grey": TOKENS.off,
        "gray": TOKENS.off,
    }.get(str(level or "").lower(), TOKENS.off)
