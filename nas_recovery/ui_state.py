from __future__ import annotations

from dataclasses import dataclass
from tkinter import ttk


@dataclass(frozen=True)
class NasUiState:
    busy: bool
    disk_selected: bool
    image_active: bool

    @property
    def can_scan(self) -> bool:
        return not self.busy

    @property
    def can_use_disk_actions(self) -> bool:
        return self.disk_selected and not self.busy

    @property
    def can_start_image(self) -> bool:
        return self.disk_selected and not self.busy

    @property
    def can_cancel_image(self) -> bool:
        return self.busy and self.image_active

    @property
    def can_open_secondary_tools(self) -> bool:
        return not self.busy


def _walk_widgets(widget):
    for child in widget.winfo_children():
        yield child
        yield from _walk_widgets(child)


def _button_by_text(root, text: str):
    for widget in _walk_widgets(root):
        if isinstance(widget, ttk.Button):
            try:
                if str(widget.cget("text")) == text:
                    return widget
            except Exception:
                pass
    return None


def apply_nas_button_states(window) -> NasUiState:
    worker = getattr(window, "_worker", None)
    busy = bool(worker and worker.is_alive())
    selected = getattr(window, "selected_disk", None) is not None
    image_active = bool(getattr(window, "_image_operation_active", False))
    state = NasUiState(busy=busy, disk_selected=selected, image_active=image_active)

    mapping = {
        "↻ Datenträger erkennen": state.can_scan,
        "Windows-Details": state.can_use_disk_actions,
        "SMART lesen": state.can_use_disk_actions,
        "Read-only Lesetest (4 MiB)": state.can_use_disk_actions,
        "Image erstellen / fortsetzen": state.can_start_image,
        "…": state.can_use_disk_actions,
        "0. Fehlende Festplatte suchen": state.can_open_secondary_tools,
        "3. RAID-Image-Analyse öffnen": state.can_open_secondary_tools,
        "4. NAS-Netzwerk prüfen": state.can_open_secondary_tools,
    }
    for text, enabled in mapping.items():
        button = _button_by_text(window, text)
        if button is not None:
            button.configure(state="normal" if enabled else "disabled")

    cancel = _button_by_text(window, "Abbrechen")
    if cancel is not None:
        cancel.configure(state="normal" if state.can_cancel_image else "disabled")
    return state


def install_nas_ui_state_machine(window):
    """Install a small state machine so impossible actions are visibly disabled.

    This follows the InteractionCore principle that unavailable actions are not
    merely rejected after a click; they are rendered disabled before the user can
    trigger them.
    """
    if getattr(window, "_nas_ui_state_machine_installed", False):
        return
    window._nas_ui_state_machine_installed = True
    window._image_operation_active = False

    original_on_select = window._on_select
    original_run_worker = window._run_worker
    original_start_image = window.start_image

    def on_select(event=None):
        result = original_on_select(event)
        apply_nas_button_states(window)
        return result

    def run_worker(name, fn, done):
        def wrapped_done(result):
            try:
                return done(result)
            finally:
                if str(name).startswith("Sektorweises Image"):
                    window._image_operation_active = False
                window.after(0, lambda: apply_nas_button_states(window))

        result = original_run_worker(name, fn, wrapped_done)
        window.after(10, lambda: apply_nas_button_states(window))
        return result

    def start_image():
        window._image_operation_active = True
        apply_nas_button_states(window)
        try:
            return original_start_image()
        finally:
            worker = getattr(window, "_worker", None)
            if not (worker and worker.is_alive()):
                window._image_operation_active = False
                apply_nas_button_states(window)

    window._on_select = on_select
    window._run_worker = run_worker
    window.start_image = start_image

    image_button = _button_by_text(window, "Image erstellen / fortsetzen")
    if image_button is not None:
        image_button.configure(command=window.start_image)

    def tick():
        try:
            if not window.winfo_exists():
                return
            apply_nas_button_states(window)
            window.after(250, tick)
        except Exception:
            return

    apply_nas_button_states(window)
    window.after(250, tick)
