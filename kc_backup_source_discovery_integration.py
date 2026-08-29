from __future__ import annotations

from tkinter import messagebox, ttk

from kc_backup_program_registry import default_registry
from kc_backup_program_store import load_program_registry
from kc_backup_source_discovery_ui import SourceDiscoveryWindow


def _find_button_by_text(root, text: str):
    stack = list(root.winfo_children())
    while stack:
        widget = stack.pop(0)
        try:
            if isinstance(widget, ttk.Button) and str(widget.cget("text")) == text:
                return widget
        except Exception:
            pass
        try:
            stack.extend(widget.winfo_children())
        except Exception:
            pass
    return None


def enable_source_discovery(App):
    if getattr(App, "_kc_source_discovery_enabled", False):
        return
    original_build = App._build

    def open_kc_source_discovery(self):
        try:
            path = self.store.path.parent / "KC_BACKUP_PROGRAMS.json"
            registry = load_program_registry(path, default_registry())
        except Exception as exc:
            messagebox.showerror(
                "KC Quellen finden",
                f"Programmregister konnte nicht sicher gelesen werden:\n{exc}",
                parent=self,
            )
            return None
        return SourceDiscoveryWindow(self, registry=registry)

    def build_with_source_discovery(self):
        original_build(self)
        anchor = _find_button_by_text(self, "KC Programme") or _find_button_by_text(self, "↻ Status")
        if anchor is not None:
            button = ttk.Button(anchor.master, text="KC Quellen finden", command=self.open_kc_source_discovery)
            button.pack(side="right", padx=(0, 8))
            self.btn_kc_source_discovery = button

    App.open_kc_source_discovery = open_kc_source_discovery
    App._build = build_with_source_discovery
    App._kc_source_discovery_enabled = True
