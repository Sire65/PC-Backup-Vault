from __future__ import annotations

from tkinter import ttk

from .inventory_ui import NasInventoryWindow
from .ssh_readonly import SshReadOnlyReport


def _find_ssh_frame(window):
    for child in window.winfo_children():
        for nested in child.winfo_children():
            try:
                if isinstance(nested, ttk.LabelFrame) and str(nested.cget("text")) == "3. SSH Read-only Systemcheck":
                    return nested
            except Exception:
                pass
    return None


def enable_nas_inventory_view(NasNetworkWindowClass):
    """Expose storage inventory only after a successful read-only SSH report exists."""
    if getattr(NasNetworkWindowClass, "_inventory_view_enabled", False):
        return NasNetworkWindowClass

    original_build = NasNetworkWindowClass._build
    original_refresh = NasNetworkWindowClass._refresh_controls
    original_done = NasNetworkWindowClass._done
    original_host_changed = NasNetworkWindowClass._host_changed

    def open_inventory(self):
        report = getattr(self, "_last_ssh_report", None)
        if report is None:
            return
        existing = getattr(self, "_inventory_window", None)
        try:
            if existing is not None and existing.winfo_exists():
                existing.destroy()
        except Exception:
            pass
        self._inventory_window = NasInventoryWindow(self, report)
        return self._inventory_window

    def wrapped_build(self, *args, **kwargs):
        result = original_build(self, *args, **kwargs)
        frame = _find_ssh_frame(self)
        if frame is not None:
            self.btn_inventory = ttk.Button(
                frame,
                text="NAS-Datenstruktur anzeigen",
                command=lambda: open_inventory(self),
                state="disabled",
            )
            self.btn_inventory.grid(row=4, column=0, columnspan=2, sticky="w", pady=(7, 0))
            ttk.Label(
                frame,
                text="Wird erst nach erfolgreichem Read-only-Systemcheck freigegeben.",
                style="Muted.TLabel",
            ).grid(row=4, column=2, columnspan=3, sticky="w", padx=(8, 0), pady=(7, 0))
        return result

    def wrapped_refresh(self, *args, **kwargs):
        result = original_refresh(self, *args, **kwargs)
        button = getattr(self, "btn_inventory", None)
        if button is not None:
            worker = getattr(self, "_worker", None)
            busy = bool(worker and worker.is_alive())
            ready = isinstance(getattr(self, "_last_ssh_report", None), SshReadOnlyReport) and not busy
            button.configure(state="normal" if ready else "disabled")
        return result

    def wrapped_done(self, callback, result):
        if isinstance(result, SshReadOnlyReport):
            self._last_ssh_report = result
        return original_done(self, callback, result)

    def wrapped_host_changed(self, *args, **kwargs):
        self._last_ssh_report = None
        return original_host_changed(self, *args, **kwargs)

    NasNetworkWindowClass._build = wrapped_build
    NasNetworkWindowClass._refresh_controls = wrapped_refresh
    NasNetworkWindowClass._done = wrapped_done
    NasNetworkWindowClass._host_changed = wrapped_host_changed
    NasNetworkWindowClass.open_inventory = open_inventory
    NasNetworkWindowClass._inventory_view_enabled = True
    return NasNetworkWindowClass
