from __future__ import annotations

from tkinter import ttk

from .raid_workspace import RaidWorkspaceWindow


def enable_raid_workspace(NasRecoveryWindowClass):
    """Add the RAID image workspace as an isolated submodule.

    This adapter intentionally does not move RAID logic into the main NAS window.
    The host stays focused on physical-disk read-only diagnostics and imaging;
    RAID work starts only after images exist.
    """
    if getattr(NasRecoveryWindowClass, "_raid_workspace_enabled", False):
        return NasRecoveryWindowClass

    original_build = NasRecoveryWindowClass._build

    def open_raid_workspace(self):
        existing = getattr(self, "_raid_workspace_window", None)
        try:
            if existing is not None and existing.winfo_exists():
                existing.deiconify()
                existing.lift()
                existing.focus_force()
                return existing
        except Exception:
            pass
        win = RaidWorkspaceWindow(self)
        self._raid_workspace_window = win
        return win

    def wrapped_build(self, *args, **kwargs):
        result = original_build(self, *args, **kwargs)
        bar = ttk.Frame(self, style="Surface.TFrame", padding=(16, 0, 16, 8))
        bar.pack(fill="x", before=self.winfo_children()[-1])
        ttk.Button(
            bar,
            text="3. RAID-Image-Analyse öffnen",
            command=lambda: open_raid_workspace(self),
        ).pack(side="left")
        ttk.Label(
            bar,
            text="Erst nach dem Imaging: Mitglied-Images prüfen, dokumentieren und Recovery-Engines vergleichen.",
            style="Muted.TLabel",
        ).pack(side="left", padx=(10, 0))
        return result

    NasRecoveryWindowClass._build = wrapped_build
    NasRecoveryWindowClass.open_raid_workspace = open_raid_workspace
    NasRecoveryWindowClass._raid_workspace_enabled = True
    return NasRecoveryWindowClass
