from __future__ import annotations

from pathlib import Path
from tkinter import messagebox, ttk


def _unique_existing(paths):
    """Return unique non-empty source paths while preserving order.

    Existence is deliberately not enforced here: removable drives may disappear
    between inventory and backup configuration. The normal Backup Vault preflight
    remains authoritative before a backup actually runs.
    """
    out = []
    seen = set()
    for value in paths or []:
        text = str(value or "").strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def inventory_backup_sources(finder):
    """Selected inventory rows win; otherwise return the configured scan roots."""
    selected = _unique_existing(finder.selected_paths())
    if selected:
        return selected, "SELECTION"
    return _unique_existing(getattr(finder, "roots", []) or []), "ROOTS"


def enable_inventory_backup_handoff(app_class, backup_assistant_cls):
    """Add a safe handoff from Project Finder to the normal Backup Assistant.

    Project Finder never performs the backup itself. It only transfers the chosen
    source paths. Target, backup mode, verification, One-Touch and scheduling stay
    inside the existing Backup Vault assistant and plan model.
    """
    if getattr(app_class, "_inventory_backup_handoff_v190", False):
        return app_class

    original_open = app_class.open_project_finder

    def _attach_button(app, win):
        try:
            workspace = next((w for w in win.winfo_children() if hasattr(w, "finder")), None)
            if workspace is None or getattr(workspace, "_backup_handoff_button_v190", None):
                return
            finder = workspace.finder

            bar = ttk.Frame(workspace)
            # Place directly above the existing recovery bar / at the bottom of the workspace.
            bar.pack(fill="x", padx=12, pady=(0, 8))

            def handoff():
                sources, mode = inventory_backup_sources(finder)
                if not sources:
                    messagebox.showinfo(
                        "Als Backup-Job übernehmen",
                        "Bitte zuerst mindestens ein Laufwerk/Verzeichnis zur Inventur hinzufügen "
                        "oder gefundene Dateien markieren.",
                        parent=win,
                    )
                    return

                if mode == "ROOTS":
                    ok = messagebox.askyesno(
                        "Als Backup-Job übernehmen",
                        "Es sind keine einzelnen Inventurtreffer markiert.\n\n"
                        f"Sollen stattdessen die {len(sources)} ausgewählten Suchbereich(e) "
                        "an den Backup-Assistenten übergeben werden?",
                        parent=win,
                    )
                    if not ok:
                        return

                assistant = backup_assistant_cls(app)
                assistant.data["task"] = "BACKUP"
                assistant.data["paths"] = list(sources)
                assistant.data["name"] = (
                    "Inventur-Auswahl Backup" if mode == "SELECTION" else "Inventur-Laufwerk Backup"
                )
                # Start at source review so the transferred paths are visible before
                # target, mode, verification and scheduler are configured.
                assistant.step = 1
                assistant.render()
                try:
                    assistant.subtitle.configure(
                        text=(
                            "Aus Inventur übernommen – Quellen prüfen; danach Ziel, "
                            "Sicherungsart und Zeitplan festlegen."
                        )
                    )
                except Exception:
                    pass

            button = ttk.Button(
                bar,
                text="💾 Auswahl als Backup-Job übernehmen…",
                command=handoff,
            )
            button.pack(side="right")
            ttk.Label(
                bar,
                text="Inventur findet · Backup Vault sichert",
            ).pack(side="right", padx=(0, 10))
            workspace._backup_handoff_button_v190 = button
        except Exception:
            # Inventory must remain usable even if this comfort integration cannot attach.
            return

    def open_project_finder(self):
        win = original_open(self)
        try:
            self.after(0, lambda: _attach_button(self, win))
        except Exception:
            _attach_button(self, win)
        return win

    app_class.open_project_finder = open_project_finder
    app_class._inventory_backup_handoff_v190 = True
    return app_class
