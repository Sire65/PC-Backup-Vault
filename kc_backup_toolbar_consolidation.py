from __future__ import annotations

from tkinter import ttk


def backup_central_button_labels() -> tuple[str, ...]:
    return (
        "KC Programme",
        "KC Quellen finden",
        "🗓 Backup-Kalender",
        "Automatik: AUS",
        "… Scheduler: STARTET",
    )


def enable_backup_central_toolbar(App):
    """Move Backup-Central controls out of the crowded system-status row.

    Existing integration buttons are hidden after the wrapped build completes and
    equivalent controls are created in one dedicated row. Commands and safety
    semantics stay unchanged; this module changes layout only.
    """
    if getattr(App, "_kc_backup_central_toolbar_enabled", False):
        return
    required = (
        "_kc_backup_central_enabled",
        "_kc_scheduler_observability_enabled",
        "_kc_source_discovery_enabled",
    )
    if not all(getattr(App, name, False) for name in required):
        raise RuntimeError("Backup-Central UI-Erweiterungen müssen vor Toolbar-Konsolidierung aktiviert werden")

    original_build = App._build

    def build_with_backup_central_toolbar(self):
        original_build(self)

        old_buttons = tuple(
            widget
            for widget in (
                getattr(self, "btn_kc_programs", None),
                getattr(self, "btn_kc_source_discovery", None),
                getattr(self, "btn_backup_calendar", None),
                getattr(self, "btn_scheduler_automation", None),
                getattr(self, "btn_scheduler_runtime", None),
            )
            if widget is not None
        )
        if not old_buttons:
            return

        status_bar = old_buttons[0].master
        for widget in old_buttons:
            try:
                widget.pack_forget()
            except Exception:
                pass

        bar = ttk.LabelFrame(self, text="Backup Central", padding=(10, 5))
        try:
            bar.pack(fill="x", padx=12, pady=(0, 6), after=status_bar)
        except Exception:
            bar.pack(fill="x", padx=12, pady=(0, 6))

        self.btn_kc_programs = ttk.Button(bar, text="KC Programme", command=self.open_kc_programs)
        self.btn_kc_programs.pack(side="left", padx=(0, 6))

        self.btn_kc_source_discovery = ttk.Button(bar, text="KC Quellen finden", command=self.open_kc_source_discovery)
        self.btn_kc_source_discovery.pack(side="left", padx=(0, 6))

        self.btn_backup_calendar = ttk.Button(bar, text="🗓 Backup-Kalender", command=self.open_backup_calendar)
        self.btn_backup_calendar.pack(side="left", padx=(0, 14))

        self.btn_scheduler_automation = ttk.Button(
            bar,
            text="Automatik: AUS",
            command=self._kc_toggle_scheduler_automation,
        )
        self.btn_scheduler_automation.pack(side="right", padx=(6, 0))

        self.btn_scheduler_runtime = ttk.Button(
            bar,
            text="… Scheduler: STARTET",
            command=self._kc_show_scheduler_status,
        )
        self.btn_scheduler_runtime.pack(side="right", padx=(6, 0))

        ttk.Label(
            bar,
            text="Restore-Test nie unbeaufsichtigt · KC MAXIMUM",
        ).pack(side="right", padx=(0, 8))

        self.backup_central_toolbar = bar
        try:
            self.after(0, self._kc_refresh_scheduler_indicator)
        except Exception:
            pass

    App._build = build_with_backup_central_toolbar
    App._kc_backup_central_toolbar_enabled = True
