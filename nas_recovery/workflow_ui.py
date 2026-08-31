from __future__ import annotations

from tkinter import ttk

from .missing_disk_ui import MissingDiskWindow
from .network_ui import NasNetworkWindow
from .recovery_assistant_ui import RecoveryAssistantWindow
from .ui_state import install_nas_ui_state_machine


def enable_nas_workflow_ui(NasRecoveryWindowClass):
    """Add workflow steps and install logical enable/disable behavior.

    Integration remains UI-only: physical-disk, missing-disk and network business
    logic stay in their dedicated read-only services.
    """
    if getattr(NasRecoveryWindowClass, "_workflow_ui_enabled", False):
        return NasRecoveryWindowClass

    original_init = NasRecoveryWindowClass.__init__

    def open_missing_disk_search(self):
        existing = getattr(self, "_missing_disk_window", None)
        try:
            if existing is not None and existing.winfo_exists():
                existing.deiconify(); existing.lift(); existing.focus_force(); return existing
        except Exception:
            pass
        win = MissingDiskWindow(self)
        self._missing_disk_window = win
        return win

    def open_network_diagnostics(self):
        existing = getattr(self, "_network_window", None)
        try:
            if existing is not None and existing.winfo_exists():
                existing.deiconify(); existing.lift(); existing.focus_force(); return existing
        except Exception:
            pass
        win = NasNetworkWindow(self)
        self._network_window = win
        return win

    def open_recovery_assistant(self):
        existing = getattr(self, "_recovery_assistant_window", None)
        try:
            if existing is not None and existing.winfo_exists():
                existing.deiconify(); existing.lift(); existing.focus_force(); return existing
        except Exception:
            pass
        win = RecoveryAssistantWindow(self, selected_disk=getattr(self, "selected_disk", None))
        self._recovery_assistant_window = win
        return win

    def wrapped_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        footer = self.winfo_children()[-1]

        finder_bar = ttk.Frame(self, style="Surface.TFrame", padding=(16, 0, 16, 6))
        finder_bar.pack(fill="x", before=footer)
        ttk.Button(finder_bar, text="0. Fehlende Festplatte suchen", command=lambda: open_missing_disk_search(self)).pack(side="left")
        ttk.Label(finder_bar, text="Auch Platten ohne Explorer-Laufwerksbuchstaben, offline/RAW sowie PnP-/Storage-Abweichungen read-only suchen.", style="Muted.TLabel").pack(side="left", padx=(10, 0))

        assistant_bar = ttk.Frame(self, style="Surface.TFrame", padding=(16, 0, 16, 6))
        assistant_bar.pack(fill="x", before=footer)
        ttk.Button(assistant_bar, text="Recovery-Assistent öffnen", command=lambda: open_recovery_assistant(self)).pack(side="left")
        ttk.Label(assistant_bar, text="Geführter Image-first-Ablauf; gesperrte Schritte bleiben ausgegraut, bis alle Voraussetzungen erfüllt sind.", style="Muted.TLabel").pack(side="left", padx=(10, 0))

        network_bar = ttk.Frame(self, style="Surface.TFrame", padding=(16, 0, 16, 8))
        network_bar.pack(fill="x", before=footer)
        ttk.Button(network_bar, text="4. NAS-Netzwerk prüfen", command=lambda: open_network_diagnostics(self)).pack(side="left")
        ttk.Label(network_bar, text="Unabhängig von der Plattenanalyse: Host/IP, SMB, Web und SSH-Erreichbarkeit nur lesend prüfen.", style="Muted.TLabel").pack(side="left", padx=(10, 0))
        install_nas_ui_state_machine(self)

    NasRecoveryWindowClass.__init__ = wrapped_init
    NasRecoveryWindowClass.open_missing_disk_search = open_missing_disk_search
    NasRecoveryWindowClass.open_network_diagnostics = open_network_diagnostics
    NasRecoveryWindowClass.open_recovery_assistant = open_recovery_assistant
    NasRecoveryWindowClass._workflow_ui_enabled = True
    return NasRecoveryWindowClass
