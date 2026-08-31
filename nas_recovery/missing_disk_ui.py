from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk

from framework_core_adapters import TOKENS, apply_design_adapter, configure_table, normalize_window_geometry, status_color
from .missing_disk import MissingDiskDetector


class MissingDiskWindow(tk.Toplevel):
    """Read-only assistant for disks that are absent from Windows Explorer."""

    def __init__(self, parent, detector: MissingDiskDetector | None = None):
        super().__init__(parent)
        self.detector = detector or MissingDiskDetector()
        self._worker: threading.Thread | None = None
        self.title("PC Backup Vault – Fehlende Festplatte suchen")
        self.configure(bg=TOKENS.bg)
        apply_design_adapter(self)
        normalize_window_geometry(self, 1220, 760, 980, 620)
        self._build()
        self.after(250, self.run_scan)

    def _build(self):
        header = ttk.Frame(self, style="Surface.TFrame", padding=(18, 13))
        header.pack(fill="x")
        left = ttk.Frame(header, style="Surface.TFrame")
        left.pack(side="left", fill="x", expand=True)
        ttk.Label(left, text="Fehlende Festplatte suchen", style="Title.TLabel").pack(anchor="w")
        ttk.Label(left, text="Read-only Windows-Speicherinventur – auch Datenträger ohne Explorer-Laufwerksbuchstaben", style="Muted.TLabel").pack(anchor="w")
        ttk.Button(header, text="Schließen", command=self.destroy).pack(side="right")

        warning = tk.Frame(self, bg="#fff7ed", highlightbackground="#fdba74", highlightthickness=1, padx=12, pady=9)
        warning.pack(fill="x", padx=16, pady=(12, 8))
        tk.Label(warning, text="WICHTIG: Bei wertvollen Daten NICHT initialisieren, formatieren, reparieren oder 'Datenträger online' erzwingen.", bg="#fff7ed", fg="#9a3412", font=(TOKENS.font_family, 9, "bold")).pack(anchor="w")

        body = ttk.Frame(self, style="Vault.TFrame", padding=(16, 4, 16, 12))
        body.pack(fill="both", expand=True)
        toolbar = ttk.Frame(body, style="Vault.TFrame")
        toolbar.pack(fill="x", pady=(0, 8))
        self.scan_btn = ttk.Button(toolbar, text="Jetzt alle Windows-Speicherebenen prüfen", command=self.run_scan)
        self.scan_btn.pack(side="left")
        self.state_label = ttk.Label(toolbar, text="Bereit", style="Muted.TLabel")
        self.state_label.pack(side="left", padx=(10, 0))

        findings_box = ttk.LabelFrame(body, text="Auffälligkeiten / Hinweise", padding=8)
        findings_box.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(findings_box, height=12)
        configure_table(self.tree, [
            ("level", "Stufe", 90, "center"),
            ("disk", "Disk", 70, "center"),
            ("title", "Befund", 290, "w"),
            ("detail", "Erklärung", 700, "w"),
        ])
        y = ttk.Scrollbar(findings_box, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=y.set)
        self.tree.pack(side="left", fill="both", expand=True)
        y.pack(side="right", fill="y")

        details = ttk.LabelFrame(body, text="Was wird geprüft?", padding=9)
        details.pack(fill="x", pady=(8, 0))
        ttk.Label(details, text="Get-Disk · Get-PhysicalDisk · Partitionen · Volumes/Laufwerksbuchstaben · PnP-Diskgeräte. Es werden ausschließlich Abfragen ausgeführt; keine Änderung an der Platte.", style="Muted.TLabel", wraplength=1120, justify="left").pack(anchor="w")

    def _set_busy(self, busy: bool, text: str):
        self.scan_btn.configure(state="disabled" if busy else "normal")
        self.state_label.configure(text=text)

    def run_scan(self):
        if self._worker and self._worker.is_alive():
            return
        self._set_busy(True, "Prüfung läuft …")
        for iid in self.tree.get_children(""):
            self.tree.delete(iid)

        def work():
            try:
                _snapshot, findings = self.detector.run()
            except Exception as exc:
                self.after(0, lambda: self._error(exc))
                return
            self.after(0, lambda: self._show_findings(findings))

        self._worker = threading.Thread(target=work, daemon=True)
        self._worker.start()

    def _show_findings(self, findings):
        level_text = {"red": "KRITISCH", "yellow": "ACHTUNG", "green": "OK"}
        for idx, finding in enumerate(findings):
            self.tree.insert("", "end", iid=str(idx), values=(level_text.get(finding.severity, finding.severity), finding.disk_number if finding.disk_number is not None else "–", finding.title, finding.detail))
        critical = sum(1 for f in findings if f.severity == "red")
        warnings = sum(1 for f in findings if f.severity == "yellow")
        self._set_busy(False, f"Fertig · {critical} kritisch · {warnings} Hinweis(e)")

    def _error(self, exc):
        self._set_busy(False, "Fehler")
        messagebox.showerror("Fehlende Festplatte suchen", str(exc), parent=self)
