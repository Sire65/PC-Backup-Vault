from __future__ import annotations

import tkinter as tk
from tkinter import ttk


def apply_heartbeat_led_v180(AppClass):
    """Add a small heartbeat indicator to the system status bar.

    The LED flashes briefly whenever the telemetry heartbeat is attempted and
    remains visually tied to the actual reporter callback, not to a timer in the UI.
    """

    original_build = AppClass._build

    def _build(self):
        original_build(self)

        sysbar = None
        for child in self.winfo_children():
            if not isinstance(child, tk.Frame):
                continue
            for sub in child.winfo_children():
                try:
                    if isinstance(sub, tk.Label) and str(sub.cget("text")) == "Systemstatus":
                        sysbar = child
                        break
                except Exception:
                    pass
            if sysbar is not None:
                break

        if sysbar is None:
            return

        frame = tk.Frame(sysbar, bg="#f8fafc")
        frame.pack(side="left", padx=(2, 12))
        tk.Label(
            frame,
            text="♥",
            bg="#f8fafc",
            fg="#64748b",
            font=("Segoe UI Symbol", 11, "bold"),
        ).pack(side="left", padx=(0, 3))

        canvas = tk.Canvas(frame, width=18, height=20, bg="#f8fafc", highlightthickness=0)
        canvas.pack(side="left")
        dot = canvas.create_oval(4, 5, 14, 15, fill="#94a3b8", outline="#64748b")

        label = tk.Label(
            frame,
            text="Heartbeat",
            bg="#f8fafc",
            fg="#0f172a",
            font=("Segoe UI", 8, "bold"),
        )
        label.pack(side="left", padx=(2, 0))

        self._heartbeat_led_canvas_v180 = canvas
        self._heartbeat_led_dot_v180 = dot
        self._heartbeat_led_label_v180 = label
        self._heartbeat_led_after_v180 = None

    AppClass._build = _build

    def heartbeat_pulse_v180(self, success=None):
        canvas = getattr(self, "_heartbeat_led_canvas_v180", None)
        dot = getattr(self, "_heartbeat_led_dot_v180", None)
        if canvas is None or dot is None:
            return

        if success is True:
            pulse_color = "#16a34a"
        elif success is False:
            pulse_color = "#dc2626"
        else:
            pulse_color = "#2563eb"

        try:
            canvas.itemconfigure(dot, fill=pulse_color)
            old = getattr(self, "_heartbeat_led_after_v180", None)
            if old:
                try:
                    self.after_cancel(old)
                except Exception:
                    pass

            def fade():
                try:
                    canvas.itemconfigure(dot, fill="#94a3b8")
                except Exception:
                    pass

            self._heartbeat_led_after_v180 = self.after(1200, fade)
        except Exception:
            pass

    AppClass.heartbeat_pulse_v180 = heartbeat_pulse_v180
