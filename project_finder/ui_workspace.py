from __future__ import annotations

from tkinter import BOTH, ttk

from .development_dashboard import DevelopmentDashboard
from .ui_changes import ChangesSinceLastTab
from .ui_git_status import GitStatusTab
from .ui_job_history import JobHistoryTab
from .ui_tab import ProjectFinderTab


class ProjectInventoryWorkspace(ttk.Frame):
    """Single host frame for the future PC Backup Vault integration.

    Keeps all new inventory functions behind one isolated tab and does not modify
    existing backup controls, backup scheduling or B2 backup behavior.
    """

    def __init__(
        self,
        master,
        *,
        quarantine_root: str | None = None,
        get_development_summary=None,
        get_git_rows=None,
        job_output_root: str | None = None,
    ):
        super().__init__(master)
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=BOTH, expand=True)

        self.finder = ProjectFinderTab(self.notebook, quarantine_root=quarantine_root)
        self.dashboard = DevelopmentDashboard(
            self.notebook,
            get_scan_items=lambda: self.finder.items,
            get_development_summary=get_development_summary,
        )
        self.changes = ChangesSinceLastTab(self.notebook)
        self.git_status = GitStatusTab(self.notebook, get_rows=get_git_rows)
        self.job_history = JobHistoryTab(self.notebook, output_root=job_output_root)

        self.notebook.add(self.dashboard, text="Übersicht")
        self.notebook.add(self.finder, text="Festplatten-Analyse")
        self.notebook.add(self.changes, text="Neu seit letzter Analyse")
        self.notebook.add(self.git_status, text="Git / Updates")
        self.notebook.add(self.job_history, text="Planjobs / Verlauf")

        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

    def _on_tab_changed(self, _event=None):
        current = self.notebook.nametowidget(self.notebook.select())
        if current is self.git_status:
            self.git_status.refresh()
        elif current is self.job_history:
            self.job_history.refresh()
