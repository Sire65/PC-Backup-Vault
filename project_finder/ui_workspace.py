from __future__ import annotations

from tkinter import BOTH, X, messagebox, ttk

from .development_dashboard import DevelopmentDashboard
from .recovery_branch import create_recovery_branches, validate_recovery_preview
from .ui_changes import ChangesSinceLastTab
from .ui_git_status import GitStatusTab
from .ui_job_history import JobHistoryTab
from .ui_source_candidates import SourceCandidatesTab
from .ui_tab import ProjectFinderTab


class ProjectInventoryWorkspace(ttk.Frame):
    """Single host frame for the PC Backup Vault Project Finder integration.

    Keeps inventory and recovery functions isolated from backup controls,
    scheduling and B2 backup behavior.
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
        self.source_candidates = SourceCandidatesTab(self.notebook, get_scan_items=lambda: self.finder.items)
        self.job_history = JobHistoryTab(self.notebook, output_root=job_output_root)

        self.notebook.add(self.dashboard, text="Übersicht")
        self.notebook.add(self.finder, text="Festplatten-Analyse")
        self.notebook.add(self.source_candidates, text="Quellstand-Kandidaten")
        self.notebook.add(self.changes, text="Neu seit letzter Analyse")
        self.notebook.add(self.git_status, text="Git / Updates")
        self.notebook.add(self.job_history, text="Planjobs / Verlauf")

        recovery_bar = ttk.Frame(self)
        recovery_bar.pack(fill=X, padx=12, pady=(0, 10))
        ttk.Label(
            recovery_bar,
            text="Recovery schreibt niemals nach main. Branch-Erzeugung enthält noch keine Dateien.",
        ).pack(side="left")
        ttk.Button(
            recovery_bar,
            text="Recovery-Branches anlegen…",
            command=self.create_recovery_branches_from_preview,
        ).pack(side="right")

        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

    def create_recovery_branches_from_preview(self):
        preview = self.finder.recovery_preview
        if not preview:
            messagebox.showinfo(
                "Recovery-Branches",
                "Noch keine Recovery-Vorschau vorhanden.\n\n"
                "Bitte zuerst Festplatten-Inventur → GitHub-Vergleich → Recovery-Branch Vorschau durchführen.",
            )
            return

        groups = preview.get("groups", [])
        if not groups:
            messagebox.showinfo(
                "Recovery-Branches",
                "Die aktuelle Vorschau enthält keine freigegebenen Recovery-Kandidaten.",
            )
            return

        validation_errors = validate_recovery_preview(preview)
        if validation_errors:
            messagebox.showwarning(
                "Recovery-Branches blockiert",
                "Die Vorschau ist nicht mehr sicher freigabefähig.\n\n"
                + "\n".join(validation_errors[:8])
                + "\n\nBitte GitHub-Vergleich und Vorschau erneut durchführen.",
            )
            return

        branches = "\n".join(
            f"• {group['repo']}\n  {group['proposed_branch']} · {group['file_count']} Datei(en) vorgemerkt"
            for group in groups[:10]
        )
        if len(groups) > 10:
            branches += f"\n• … plus {len(groups) - 10} weitere Repository(s)"

        approved = messagebox.askyesno(
            "Recovery-Branches wirklich anlegen?",
            "Jetzt wird erstmals schreibend auf GitHub zugegriffen.\n\n"
            f"Es werden {len(groups)} neue Recovery-Branch(es) angelegt:\n\n{branches}\n\n"
            "WICHTIG:\n"
            "• main/master werden NICHT verändert.\n"
            "• Es werden NOCH KEINE Dateien hochgeladen.\n"
            "• Vor dem Schreiben werden alle lokalen SHA-256-Werte erneut geprüft.\n"
            "• GITHUB_TOKEN wird nur aus der Umgebungsvariable gelesen und nicht gespeichert.\n\n"
            "Recovery-Branches jetzt anlegen?",
        )
        if not approved:
            return

        try:
            result = create_recovery_branches(preview)
        except Exception as exc:
            messagebox.showerror(
                "Recovery-Branches",
                f"Branch-Erzeugung wurde abgebrochen.\n\n{exc}\n\nmain blieb unverändert.",
            )
            return

        created = result.get("created", [])
        failed = result.get("failed", [])
        self.finder.status_var.set(
            f"Recovery-Branches · {len(created)} angelegt · {len(failed)} Fehler · 0 Dateien geschrieben · main unverändert"
        )
        created_text = "\n".join(f"• {row['repo']}: {row['branch']}" for row in created[:10]) or "Keine Branches angelegt."
        failed_text = "\n".join(f"• {row['repo']}: {row['error']}" for row in failed[:5])
        detail = f"\n\nFehler:\n{failed_text}" if failed_text else ""
        messagebox.showinfo(
            "Recovery-Branches",
            f"Angelegt: {len(created)}\nFehler: {len(failed)}\nDateien geschrieben: 0\nmain verändert: NEIN\n\n"
            f"{created_text}{detail}\n\n"
            "Der nächste Schritt ist ein separater Datei-Upload in genau diese Recovery-Branches; dafür ist eine weitere Freigabeschranke erforderlich.",
        )

    def _on_tab_changed(self, _event=None):
        current = self.notebook.nametowidget(self.notebook.select())
        if current is self.git_status:
            self.git_status.refresh()
        elif current is self.source_candidates:
            self.source_candidates.refresh()
        elif current is self.job_history:
            self.job_history.refresh()
