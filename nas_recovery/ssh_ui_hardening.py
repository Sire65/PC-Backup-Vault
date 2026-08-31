from __future__ import annotations


def enable_ssh_ui_hardening(NasNetworkWindowClass):
    """Adapter hardening: clear transient SSH password input after every error path.

    This extends the existing Framework-Studio-aligned window instead of creating
    a replacement Core or duplicating SSH business logic.
    """
    if getattr(NasNetworkWindowClass, "_ssh_ui_hardening_enabled", False):
        return NasNetworkWindowClass

    original_error = NasNetworkWindowClass._error

    def hardened_error(self, exc):
        try:
            self.password_var.set("")
            if hasattr(self, "ssh_hint"):
                self.ssh_hint.configure(text="Diagnose fehlgeschlagen. Passwort wurde aus der Eingabe gelöscht.")
        finally:
            return original_error(self, exc)

    NasNetworkWindowClass._error = hardened_error
    NasNetworkWindowClass._ssh_ui_hardening_enabled = True
    return NasNetworkWindowClass
