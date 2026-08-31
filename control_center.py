from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox
from dataclasses import dataclass

from framework_core_adapters import (
    TOKENS,
    apply_design_adapter,
    bind_window_escape,
    configure_table,
    normalize_window_geometry,
    status_color,
)
from function_catalog import visible_tasks


@dataclass(frozen=True)
class ModuleSpec:
    module_id: str
    title: str
    subtitle: str
    icon: str
    opener_name: str | None
    readiness: str = "ready"


MODULES = (
    ModuleSpec("backup", "Backup & Sicherung", "Dateien, Ordner, One-Touch und Sicherungspläne", "💾", None),
    ModuleSpec("cloud", "Cloud-Speicher", "Anbieter, Freikontingent, Kostenschutz und Umschaltung", "☁", "open_provider_registry"),
    ModuleSpec("disk", "Festplattenprüfung", "Datenträger erkennen, prüfen und Risiken bewerten", "🩺", "open_project_finder"),
    ModuleSpec("nas", "NAS & RAID Recovery", "Read-only Analyse, Images und virtuelle RAID-Rekonstruktion", "🗄", None, "integration"),
    ModuleSpec("finder", "Project Finder", "Projekte, Dubletten, Hashes und Bestandsaufnahme", "🔎", "open_project_finder"),
    ModuleSpec("git", "Git-Übergabe", "Projekte prüfen und kontrolliert für GitHub vorbereiten", "🐙", "open_project_finder"),
    ModuleSpec("restore", "Restore & Verifikation", "Sicherungen finden, prüfen und wiederherstellen", "♻", "open_explorer"),
    ModuleSpec("tuev", "TÜV / Diagnose", "Selbsttests, Regression, Logs und Systemzustand", "🧪", "open_tuev"),
    ModuleSpec("settings", "Einstellungen", "Ziele, Zugangsdaten, Limits und Programmoptionen", "⚙", "open_settings"),
)


class ControlCenterWindow(tk.Toplevel):
    """Leitstand/launcher. It observes modules and routes to them; product logic stays in modules."""

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("PC Backup Vault – Leitstand")
        self.configure(bg=TOKENS.bg)
        apply_design_adapter(self)
        normalize_window_geometry(self, 1280, 900, 1020, 720)
        bind_window_escape(self, self._minimize_to_host)
        self.protocol("WM_DELETE_WINDOW", self._minimize_to_host)
        self._build()
        self.after(250, self.refresh)

    def _minimize_to_host(self):
        try:
            self.withdraw()
            self.app.deiconify()
            self.app.lift()
        except Exception:
            self.destroy()

    def _module(self, module_id: str) -> ModuleSpec | None:
        return next((spec for spec in MODULES if spec.module_id == module_id), None)

    def _build(self):
        header = ttk.Frame(self, style="Surface.TFrame", padding=(18, 14))
        header.pack(fill="x")
        left = ttk.Frame(header, style="Surface.TFrame")
        left.pack(side="left", fill="x", expand=True)
        ttk.Label(left, text="PC Backup Vault", style="Title.TLabel").pack(anchor="w")
        ttk.Label(left, text="Backup, Recovery & Project Center · zentraler Leitstand", style="Muted.TLabel").pack(anchor="w", pady=(2, 0))
        ttk.Button(header, text="↻ Aktualisieren", command=self.refresh).pack(side="right", padx=(6, 0))
        ttk.Button(header, text="Hauptfenster", command=self._minimize_to_host).pack(side="right")

        self.alert = tk.Frame(self, bg="#e2e8f0", padx=14, pady=8)
        self.alert.pack(fill="x", padx=16, pady=(12, 8))
        self.alert_dot = tk.Canvas(self.alert, width=18, height=18, bg="#e2e8f0", highlightthickness=0)
        self.alert_dot.pack(side="left", padx=(0, 7))
        self.alert_dot_id = self.alert_dot.create_oval(3, 3, 15, 15, fill=TOKENS.off, outline="")
        self.alert_text = tk.Label(self.alert, text="Systemzustand wird geprüft …", bg="#e2e8f0", fg=TOKENS.text, font=(TOKENS.font_family, 9, "bold"))
        self.alert_text.pack(side="left")

        quick = ttk.LabelFrame(self, text="Was möchten Sie tun?", padding=10)
        quick.pack(fill="x", padx=16, pady=(0, 8))
        quick.columnconfigure(0, weight=1)
        quick.columnconfigure(1, weight=1)
        quick.columnconfigure(2, weight=1)
        for idx, task in enumerate(visible_tasks(advanced=False)):
            button = ttk.Button(
                quick,
                text=f"{task.title}\n{task.question}",
                command=lambda t=task: self.open_task(t.module_id),
            )
            button.grid(row=idx // 3, column=idx % 3, sticky="ew", padx=4, pady=4, ipady=5)
        ttk.Label(
            quick,
            text="Die häufigsten Aufgaben stehen hier zuerst. Technische Einzelwerkzeuge bleiben darunter verfügbar, müssen aber für normale Arbeit nicht verstanden werden.",
            style="Muted.TLabel",
            wraplength=1160,
            justify="left",
        ).grid(row=2, column=0, columnspan=3, sticky="w", padx=4, pady=(5, 0))

        body = ttk.Frame(self, style="Vault.TFrame", padding=(16, 2, 16, 14))
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(0, weight=1)

        modules_box = ttk.Frame(body, style="Vault.TFrame")
        modules_box.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        ttk.Label(modules_box, text="Alle Bereiche · für Details und Sonderfälle", style="Section.TLabel").pack(anchor="w", pady=(0, 8))
        grid = ttk.Frame(modules_box, style="Vault.TFrame")
        grid.pack(fill="both", expand=True)
        for col in range(3):
            grid.columnconfigure(col, weight=1, uniform="modules")
        for row in range(3):
            grid.rowconfigure(row, weight=1, uniform="modules")

        self.module_widgets = {}
        for idx, spec in enumerate(MODULES):
            card = tk.Frame(grid, bg=TOKENS.surface, highlightbackground=TOKENS.border, highlightthickness=1, padx=12, pady=10, cursor="hand2")
            card.grid(row=idx // 3, column=idx % 3, sticky="nsew", padx=5, pady=5)
            top = tk.Frame(card, bg=TOKENS.surface)
            top.pack(fill="x")
            tk.Label(top, text=spec.icon, bg=TOKENS.surface, font=(TOKENS.font_family, 18)).pack(side="left")
            dot = tk.Canvas(top, width=16, height=16, bg=TOKENS.surface, highlightthickness=0)
            dot.pack(side="right")
            dot_id = dot.create_oval(3, 3, 13, 13, fill=TOKENS.off, outline="")
            title = tk.Label(card, text=spec.title, bg=TOKENS.surface, fg=TOKENS.text, font=(TOKENS.font_family, 10, "bold"), anchor="w")
            title.pack(fill="x", pady=(6, 2))
            sub = tk.Label(card, text=spec.subtitle, bg=TOKENS.surface, fg=TOKENS.muted, font=(TOKENS.font_family, 8), wraplength=245, justify="left", anchor="nw")
            sub.pack(fill="both", expand=True)
            state = tk.Label(card, text="Bereit", bg=TOKENS.surface, fg=TOKENS.muted, font=(TOKENS.font_family, 8, "bold"), anchor="w")
            state.pack(fill="x", pady=(7, 0))
            for w in (card, top, title, sub, state):
                w.bind("<Button-1>", lambda _e, s=spec: self.open_module(s))
            self.module_widgets[spec.module_id] = (dot, dot_id, state)

        side = ttk.Frame(body, style="Vault.TFrame")
        side.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        ttk.Label(side, text="Systemübersicht", style="Section.TLabel").pack(anchor="w", pady=(0, 8))
        table_frame = ttk.Frame(side, style="Surface.TFrame", padding=1)
        table_frame.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(table_frame, height=12)
        configure_table(self.tree, [
            ("component", "Bereich", 170, "w"),
            ("status", "Status", 90, "w"),
            ("detail", "Hinweis", 260, "w"),
        ])
        sy = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sy.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sy.pack(side="right", fill="y")

        gov = ttk.LabelFrame(side, text="Technik / Framework", padding=10)
        gov.pack(fill="x", pady=(10, 0))
        self.gov_label = ttk.Label(gov, style="Muted.TLabel", wraplength=430, justify="left")
        self.gov_label.pack(anchor="w")
        self.gov_label.configure(text=(
            "Für die normale Bedienung nicht erforderlich. UI-Verträge: DesignCore · WindowCore · TableCore · NavigationCore. "
            "Tkinter nutzt Adapter; Fachlogik bleibt in den Modulen."
        ))

    def open_task(self, module_id: str):
        spec = self._module(module_id)
        if spec is None:
            messagebox.showwarning("Schnellstart", "Diese Aufgabe ist noch keinem Bereich zugeordnet.", parent=self)
            return
        self.open_module(spec)

    def _status_snapshot(self):
        rows = []
        raw = getattr(self.app, "_system_states", {}) or {}
        labels = {
            "neon": "Neon / Datenbank",
            "b2": "Backblaze B2",
            "vault": "Tresor / Schlüssel",
            "scheduler": "Scheduler",
            "verify": "Verify / TÜV",
            "kc": "KC Kommunikation",
        }
        for key, label in labels.items():
            value = raw.get(key, {})
            if isinstance(value, dict):
                level = str(value.get("level") or value.get("state") or "unknown").lower()
                detail = str(value.get("detail") or value.get("message") or "")
            else:
                level = "unknown"
                detail = ""
            rows.append((key, label, level, detail))
        return rows

    def refresh(self):
        try:
            self.app.refresh_system_status()
        except Exception:
            pass
        rows = self._status_snapshot()
        for iid in self.tree.get_children(""):
            self.tree.delete(iid)
        severe = 0
        warnings = 0
        for key, label, level, detail in rows:
            normalized = "OK" if level in ("ok", "green") else "WARNUNG" if level in ("warn", "warning", "yellow") else "FEHLER" if level in ("error", "red") else "–"
            if normalized == "FEHLER": severe += 1
            elif normalized == "WARNUNG": warnings += 1
            self.tree.insert("", "end", values=(label, normalized, detail or "Keine Detailmeldung"))

        for spec in MODULES:
            dot, dot_id, state = self.module_widgets[spec.module_id]
            if spec.readiness == "integration":
                level, text = "warn", "Integration läuft – Sicherheitsmodul bleibt getrennt"
            elif spec.opener_name and not callable(getattr(self.app, spec.opener_name, None)):
                level, text = "off", "Noch nicht verbunden"
            else:
                level, text = "ok", "Bereit"
            dot.itemconfigure(dot_id, fill=status_color(level))
            state.configure(text=text, fg=status_color(level) if level != "off" else TOKENS.muted)

        if severe:
            level = "error"; text = f"{severe} Systemfehler erkannt – Details rechts prüfen."
        elif warnings:
            level = "warn"; text = f"{warnings} Hinweis(e) benötigen Aufmerksamkeit."
        else:
            level = "ok"; text = "Leitstand bereit. Keine kritische Systemmeldung erkannt."
        self.alert_dot.itemconfigure(self.alert_dot_id, fill=status_color(level))
        self.alert_text.configure(text=text)

    def open_module(self, spec: ModuleSpec):
        if spec.module_id == "backup":
            self._minimize_to_host()
            return
        if spec.module_id == "nas":
            messagebox.showinfo(
                "NAS & RAID Recovery",
                "NAS Migration Studio v5.6 wird derzeit als geschütztes Read-only-Modul integriert.\n\n"
                "Bis der Adapter-TÜV abgeschlossen ist, startet der Leitstand keine ungetestete Recovery-Funktion.",
                parent=self,
            )
            return
        opener = getattr(self.app, spec.opener_name or "", None)
        if not callable(opener):
            messagebox.showwarning("Modul", f"{spec.title} ist noch nicht mit dem Leitstand verbunden.", parent=self)
            return
        try:
            opener()
        except Exception as exc:
            messagebox.showerror("Modul konnte nicht geöffnet werden", f"{spec.title}\n\n{exc}", parent=self)


def enable_control_center(AppClass):
    """Attach the new Leitstand without altering backup/recovery business logic."""
    if getattr(AppClass, "_control_center_enabled", False):
        return AppClass

    original_init = AppClass.__init__

    def open_control_center(self):
        existing = getattr(self, "_control_center_window", None)
        try:
            if existing is not None and existing.winfo_exists():
                existing.deiconify(); existing.lift(); existing.focus_force(); existing.refresh(); return existing
        except Exception:
            pass
        win = ControlCenterWindow(self)
        self._control_center_window = win
        return win

    def wrapped_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self.open_control_center = lambda: open_control_center(self)
        self.after(450, self.open_control_center)

    AppClass.__init__ = wrapped_init
    AppClass.open_control_center = open_control_center
    AppClass._control_center_enabled = True
    return AppClass
