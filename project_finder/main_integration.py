from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .ui_workspace import ProjectInventoryWorkspace


def enable_project_finder(app_class):
    """Attach Project Finder to the existing PC Backup Vault App without touching backup logic."""
    if getattr(app_class, '_project_finder_enabled', False):
        return app_class

    original_build = app_class._build

    def open_project_finder(self):
        existing = getattr(self, '_project_finder_window', None)
        try:
            if existing is not None and existing.winfo_exists():
                existing.deiconify(); existing.lift(); existing.focus_force(); return existing
        except Exception:
            pass

        win = tk.Toplevel(self)
        self._project_finder_window = win
        win.title('PC Backup Vault – Inventur / Project Finder')
        win.geometry('1320x850')
        win.minsize(1040, 680)
        workspace = ProjectInventoryWorkspace(win)
        workspace.pack(fill='both', expand=True)
        win.protocol('WM_DELETE_WINDOW', win.destroy)
        return win

    def wrapped_build(self):
        original_build(self)
        try:
            # Reuse the existing top command bar so the inventory is reachable from the main program.
            top = self.winfo_children()[0]
            ttk.Button(top, text='🔎 Inventur / Project Finder', command=self.open_project_finder).pack(side='right', padx=(0, 6))
        except Exception:
            # Fallback: keep integration functional even if the host layout changes.
            ttk.Button(self, text='🔎 Inventur / Project Finder', command=self.open_project_finder).pack(fill='x', padx=12, pady=(0, 6))

    app_class.open_project_finder = open_project_finder
    app_class._build = wrapped_build
    app_class._project_finder_enabled = True
    return app_class
