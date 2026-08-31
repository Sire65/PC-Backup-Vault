from __future__ import annotations

from tkinter import ttk

from .network_ui import NasNetworkWindow
from .ui_state import install_nas_ui_state_machine


def enable_nas_workflow_ui(NasRecoveryWindowClass):
    """Add the next workflow step and install logical enable/disable behavior.

    The integration is deliberately UI-only: physical-disk and network business
    logic remain in their dedicated services.
    """
    if getattr(NasRecoveryWindowClass, "_workflow_ui_enabled", False):
        return NasRecoveryWindowClass

    original_init = NasRecoveryWindowClass.__init__

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

    def wrapped_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        # Insert the independent network step above the status footer. It can be
        # opened without choosing a physical disk because a NAS may still be live
        # on the network even when no disk is attached to this PC.
        footer = self.winfo_children()[-1]
        bar = ttk.Frame(self, style="Surface.TFrame", padding=(16, 0, 16, 8))
        bar.pack(fill="x", before=footer)
        ttk.Button(bar, text="4. NAS-Netzwerk prüfen", command=lambda: open_network_diagnostics(self)).pack(side="left")
        ttk.Label(
            bar,
            text="Unabhängig von der Plattenanalyse: Host/IP, SMB, Web und SSH-Erreichbarkeit nur lesend prüfen.",
            style="Muted.TLabel",
        ).pack(side="left", padx=(10, 0))
        install_nas_ui_state_machine(self)

    NasRecoveryWindowClass.__init__ = wrapped_init
    NasRecoveryWindowClass.open_network_diagnostics = open_network_diagnostics
    NasRecoveryWindowClass._workflow_ui_enabled = True
    return NasRecoveryWindowClass
