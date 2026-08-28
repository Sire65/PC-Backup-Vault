from __future__ import annotations

from tkinter import BOTH, ttk

from .development_dashboard import DevelopmentDashboard
from .ui_tab import ProjectFinderTab


class ProjectInventoryWorkspace(ttk.Frame):
    """Single host frame for the future PC Backup Vault integration.

    Keeps all new inventory functions behind one isolated tab and does not modify
    existing backup controls, backup scheduling or B2 backup behavior.
    """

    def __init__(self, master, *, quarantine_root: str | None = None, get_development_summary=None):
        super().__init__(master)
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=BOTH, expand=True)

        self.finder = ProjectFinderTab(self.notebook, quarantine_root=quarantine_root)
        self.dashboard = DevelopmentDashboard(
            self.notebook,
            get_scan_items=lambda: self.finder.items,
            get_development_summary=get_development_summary,
        )

        self.notebook.add(self.dashboard, text="Übersicht")
        self.notebook.add(self.finder, text="Festplatten-Analyse")

        # Chat inventory is intentionally handled inside the dashboard. Later tabs can
        # add Git comparison, job planning and update distribution without touching
        # the existing backup application's own tabs.
