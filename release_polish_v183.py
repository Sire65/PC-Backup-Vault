from __future__ import annotations

import os
import tkinter as tk
from tkinter import ttk

from config_store import APP_VERSION
from storage_v180 import _targets
from system_image_integration_v180 import SystemImageWizard


def apply_release_polish_v183(AppClass, DashboardWindowClass, ui_module):
    """Final 1.8.3 release polish: direct system-image access, target-aware dashboard and version test."""

    # Add the running application version as an explicit test item. Because the
    # consolidated test resolves ui_module.run_tuev at runtime, this appears in
    # 'Alle Tests' and is copied/saved with the rest of the test report.
    original_tuev = ui_module.run_tuev

    def run_tuev_with_version(*args, **kwargs):
        checks = list(original_tuev(*args, **kwargs) or [])
        checks.append(("APP-001", "Programmversion", "PASS", f"PC Backup Vault {APP_VERSION}"))
        return checks

    ui_module.run_tuev = run_tuev_with_version

    # Direct access to Windows system image outside the assistant.
    original_build = AppClass._build

    def app_build(self):
        original_build(self)
        try:
            for child in self.winfo_children():
                if isinstance(child, ttk.LabelFrame) and str(child.cget("text")) == "Übersicht / Wiederherstellung":
                    ttk.Button(
                        child,
                        text="🖥 Windows-Systemabbild",
                        command=lambda: SystemImageWizard(self),
                    ).pack(side="left", padx=(6, 0))
                    break
        except Exception:
            pass

    AppClass._build = app_build

    # Dashboard: dedicated target view for B2/Neon plus filesystem/USB/NAS targets.
    original_dash_build = DashboardWindowClass._build
    original_render = DashboardWindowClass._render_current_tab

    def dash_build(self):
        original_dash_build(self)
        self.tab_targets = ttk.Frame(self.nb, padding=12)
        self.nb.add(self.tab_targets, text="Speicherziele / Laufwerke")
        self._render_targets_v183()

    def render_targets(self):
        tab = self.tab_targets
        for w in tab.winfo_children():
            w.destroy()
        ttk.Label(tab, text="Speicherziele / Laufwerke", font=("Segoe UI", 15, "bold")).pack(anchor="w")
        ttk.Label(
            tab,
            text="Zeigt die für PC Backup Vault konfigurierten Ziele. USB, externe Laufwerke, Ordner und NAS werden hier gemeinsam mit B2 und Neon sichtbar.",
            wraplength=980,
        ).pack(anchor="w", pady=(4, 12))

        tree = ttk.Treeview(tab, columns=("type", "name", "path", "state", "plans"), show="headings", height=13)
        for key, title, width in [
            ("type", "Typ", 120), ("name", "Name", 190), ("path", "Pfad / Ziel", 430),
            ("state", "Status", 140), ("plans", "Verwendet von", 260),
        ]:
            tree.heading(key, text=title); tree.column(key, width=width, anchor="w")
        tree.pack(fill="both", expand=True)

        b2 = self.app.store.get_b2_runtime_config()
        b2_state = "Bereit" if b2.get("configured") else "Nicht vollständig eingerichtet"
        tree.insert("", "end", values=("Cloud", "Backblaze B2", b2.get("bucket") or "–", b2_state, "B2-Pläne"))
        prof = self.app.active_profile() or {}
        tree.insert("", "end", values=("Core", "Neon", prof.get("database") or "pc_backup_vault", "Aktiv" if self.app.active_dsn() else "Kein Zugang", "Metadaten/Core"))

        plans = list(self.app.store.data.get("plans", []) or [])
        for target in _targets(self.app.store):
            tid = target.get("id")
            path = str(target.get("path") or "")
            used = [p.get("name") or "Backup" for p in plans if p.get("filesystem_target_id") == tid]
            state = "Erreichbar" if path and os.path.exists(path) else "Derzeit nicht erreichbar"
            tree.insert("", "end", values=("Laufwerk/NAS", target.get("name") or "Backup-Ziel", path or "–", state, ", ".join(used) if used else "noch keinem Plan zugeordnet"))

        ttk.Button(tab, text="↻ Ziele aktualisieren", command=self._render_targets_v183).pack(anchor="e", pady=(10, 0))

    def render_current(self):
        try:
            idx = self.nb.index(self.nb.select())
            if hasattr(self, "tab_targets") and idx == self.nb.index(self.tab_targets):
                self._render_targets_v183(); return
        except Exception:
            pass
        return original_render(self)

    DashboardWindowClass._build = dash_build
    DashboardWindowClass._render_targets_v183 = render_targets
    DashboardWindowClass._render_current_tab = render_current
