from __future__ import annotations

from collections import deque
from datetime import datetime
import tkinter as tk
from tkinter import ttk


def apply_heartbeat_led_v180(AppClass):
    """Add a compact heart + LED tied only to real telemetry heartbeat attempts."""

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

        frame = tk.Frame(sysbar, bg="#f8fafc", cursor="hand2")
        frame.pack(side="left", padx=(2, 7))

        heart = tk.Label(
            frame,
            text="♥",
            bg="#f8fafc",
            fg="#64748b",
            font=("Segoe UI Symbol", 12, "bold"),
            cursor="hand2",
        )
        heart.pack(side="left", padx=(0, 2))

        canvas = tk.Canvas(frame, width=14, height=18, bg="#f8fafc", highlightthickness=0, cursor="hand2")
        canvas.pack(side="left")
        dot = canvas.create_oval(3, 5, 11, 13, fill="#94a3b8", outline="#64748b")

        self._heartbeat_led_frame_v180 = frame
        self._heartbeat_led_heart_v180 = heart
        self._heartbeat_led_canvas_v180 = canvas
        self._heartbeat_led_dot_v180 = dot
        self._heartbeat_last_at_v180 = None
        self._heartbeat_last_success_v180 = None
        self._heartbeat_tooltip_v180 = None
        self._heartbeat_heart_after_v180 = None
        self._heartbeat_success_history_v180 = deque(maxlen=20)

        def tooltip_text():
            when = getattr(self, "_heartbeat_last_at_v180", None)
            success = getattr(self, "_heartbeat_last_success_v180", None)
            if when is None:
                return "Heartbeat: Noch kein Lebenszeichen gesendet\nDoppelklick: erfolgreiche Heartbeats anzeigen"
            state = "erfolgreich" if success is True else ("fehlgeschlagen" if success is False else "gesendet")
            return f"Letzter Heartbeat: {when.strftime('%H:%M:%S')} – {state}\nDoppelklick: erfolgreiche Heartbeats anzeigen"

        def hide_tip(event=None):
            tip = getattr(self, "_heartbeat_tooltip_v180", None)
            if tip is not None:
                try:
                    tip.destroy()
                except Exception:
                    pass
            self._heartbeat_tooltip_v180 = None

        def show_tip(event=None):
            hide_tip()
            tip = tk.Toplevel(self)
            tip.wm_overrideredirect(True)
            try:
                tip.attributes("-topmost", True)
            except Exception:
                pass
            x = frame.winfo_rootx() + 8
            y = frame.winfo_rooty() + frame.winfo_height() + 5
            tip.geometry(f"+{x}+{y}")
            tk.Label(
                tip,
                text=tooltip_text(),
                bg="#111827",
                fg="white",
                padx=8,
                pady=5,
                relief="solid",
                bd=1,
                font=("Segoe UI", 8),
                justify="left",
            ).pack()
            self._heartbeat_tooltip_v180 = tip

        def show_history(event=None):
            hide_tip()
            win = tk.Toplevel(self)
            win.title("Heartbeat – letzte erfolgreiche Lebenszeichen")
            win.geometry("520x360")
            win.minsize(460, 280)
            win.transient(self)
            box = ttk.Frame(win, padding=12)
            box.pack(fill="both", expand=True)
            ttk.Label(box, text="Letzte erfolgreiche Heartbeats", font=("Segoe UI", 13, "bold")).pack(anchor="w")
            ttk.Label(
                box,
                text="Es werden die letzten 20 erfolgreichen Lebenszeichen dieser Programmsitzung angezeigt.",
                wraplength=480,
            ).pack(anchor="w", pady=(3, 9))
            tree = ttk.Treeview(box, columns=("nr", "datum", "zeit"), show="headings", height=10)
            tree.heading("nr", text="#")
            tree.heading("datum", text="Datum")
            tree.heading("zeit", text="Uhrzeit")
            tree.column("nr", width=50, anchor="center", stretch=False)
            tree.column("datum", width=140, anchor="center")
            tree.column("zeit", width=120, anchor="center")
            tree.pack(fill="both", expand=True)
            history = list(getattr(self, "_heartbeat_success_history_v180", []) or [])
            for idx, stamp in enumerate(reversed(history), start=1):
                tree.insert("", "end", values=(idx, stamp.strftime("%d.%m.%Y"), stamp.strftime("%H:%M:%S")))
            if not history:
                tree.insert("", "end", values=("–", "Noch kein", "erfolgreicher Beat"))
            ttk.Button(box, text="Schließen", command=win.destroy).pack(anchor="e", pady=(9, 0))

        for widget in (frame, heart, canvas):
            widget.bind("<Enter>", show_tip)
            widget.bind("<Leave>", hide_tip)
            widget.bind("<Double-Button-1>", show_history)

    AppClass._build = _build

    def heartbeat_pulse_v180(self, success=None):
        canvas = getattr(self, "_heartbeat_led_canvas_v180", None)
        dot = getattr(self, "_heartbeat_led_dot_v180", None)
        heart = getattr(self, "_heartbeat_led_heart_v180", None)
        if canvas is None or dot is None:
            return

        now = datetime.now()
        self._heartbeat_last_at_v180 = now
        self._heartbeat_last_success_v180 = success
        if success is True:
            history = getattr(self, "_heartbeat_success_history_v180", None)
            if history is not None:
                history.append(now)

        if success is True:
            state_color = "#16a34a"
        elif success is False:
            state_color = "#dc2626"
        else:
            state_color = "#2563eb"

        try:
            # LED = Zustand des letzten realen Sendeversuchs. Herz = sichtbarer Beat:
            # Bei JEDEM tatsächlichen Heartbeat kurz rot aufblinken, danach wieder grau.
            canvas.itemconfigure(dot, fill=state_color)
            if heart is not None:
                heart.configure(fg="#dc2626")
                old = getattr(self, "_heartbeat_heart_after_v180", None)
                if old:
                    try:
                        self.after_cancel(old)
                    except Exception:
                        pass

                def fade_heart():
                    try:
                        heart.configure(fg="#64748b")
                    except Exception:
                        pass

                self._heartbeat_heart_after_v180 = self.after(900, fade_heart)
        except Exception:
            pass

    AppClass.heartbeat_pulse_v180 = heartbeat_pulse_v180
