from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from framework_core_adapters import (
    TOKENS,
    apply_design_adapter,
    bind_window_escape,
    configure_table,
    normalize_window_geometry,
)
from .inventory import NasStorageInventory, inventory_from_ssh_report


class NasInventoryWindow(tk.Toplevel):
    """Read-only view over storage information already collected by SSH diagnostics."""

    def __init__(self, parent, ssh_report):
        super().__init__(parent)
        self.report = ssh_report
        self.inventory: NasStorageInventory = inventory_from_ssh_report(ssh_report)
        self.title("PC Backup Vault – NAS Datenstruktur")
        self.configure(bg=TOKENS.bg)
        apply_design_adapter(self)
        normalize_window_geometry(self, 1100, 760, 900, 620)
        bind_window_escape(self, self.destroy)
        self._build()

    def _build(self):
        header = ttk.Frame(self, style="Surface.TFrame", padding=(18, 13))
        header.pack(fill="x")
        left = ttk.Frame(header, style="Surface.TFrame")
        left.pack(side="left", fill="x", expand=True)
        ttk.Label(left, text="NAS Datenstruktur", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            left,
            text=f"{self.report.host} · nur bereits gelesene Diagnosewerte · keine Änderungen am NAS",
            style="Muted.TLabel",
        ).pack(anchor="w")
        ttk.Button(header, text="Schließen", command=self.destroy).pack(side="right")

        body = ttk.Frame(self, style="Vault.TFrame", padding=16)
        body.pack(fill="both", expand=True)

        summary = ttk.LabelFrame(body, text="Übersicht", padding=10)
        summary.pack(fill="x")
        likely = len(self.inventory.likely_data_mounts)
        text = (
            f"Mountpoints: {len(self.inventory.mounts)}   ·   Speicherbereiche: {len(self.inventory.usage)}   ·   "
            f"wahrscheinliche Datenbereiche: {likely}"
        )
        ttk.Label(summary, text=text, style="Section.TLabel").pack(anchor="w")
        hint = (
            "Datenbereiche wurden anhand typischer NAS-Pfade markiert. Noch wird nichts kopiert, repariert, gemountet oder verändert."
        )
        ttk.Label(summary, text=hint, style="Muted.TLabel").pack(anchor="w", pady=(4, 0))

        notebook = ttk.Notebook(body)
        notebook.pack(fill="both", expand=True, pady=(10, 0))

        data_tab = ttk.Frame(notebook, padding=8)
        usage_tab = ttk.Frame(notebook, padding=8)
        mount_tab = ttk.Frame(notebook, padding=8)
        notebook.add(data_tab, text="Datenbereiche")
        notebook.add(usage_tab, text="Speicherbelegung")
        notebook.add(mount_tab, text="Mountpoints")

        self.data_tree = ttk.Treeview(data_tab, height=12)
        configure_table(self.data_tree, [
            ("path", "Pfad", 420, "w"),
            ("size", "Größe", 110, "e"),
            ("used", "Belegt", 110, "e"),
            ("free", "Frei", 110, "e"),
            ("percent", "Belegt %", 90, "center"),
            ("mode", "Mount", 100, "center"),
        ])
        self.data_tree.pack(fill="both", expand=True)

        usage_by_mount = {u.mountpoint: u for u in self.inventory.usage}
        mount_by_target = {m.target: m for m in self.inventory.mounts}
        for path in self.inventory.likely_data_mounts:
            usage = usage_by_mount.get(path)
            mount = mount_by_target.get(path)
            self.data_tree.insert("", "end", values=(
                path,
                usage.size if usage else "–",
                usage.used if usage else "–",
                usage.available if usage else "–",
                usage.percent if usage else "–",
                ("nur lesen" if mount and mount.read_only else "rw/unklar" if mount else "unbekannt"),
            ))

        self.usage_tree = ttk.Treeview(usage_tab, height=12)
        configure_table(self.usage_tree, [
            ("fs", "Dateisystem/Device", 260, "w"),
            ("size", "Größe", 100, "e"),
            ("used", "Belegt", 100, "e"),
            ("free", "Frei", 100, "e"),
            ("percent", "Belegt %", 90, "center"),
            ("mount", "Mountpoint", 330, "w"),
        ])
        self.usage_tree.pack(fill="both", expand=True)
        for u in self.inventory.usage:
            self.usage_tree.insert("", "end", values=(u.filesystem, u.size, u.used, u.available, u.percent, u.mountpoint))

        self.mount_tree = ttk.Treeview(mount_tab, height=12)
        configure_table(self.mount_tree, [
            ("source", "Quelle", 260, "w"),
            ("target", "Ziel", 330, "w"),
            ("type", "Typ", 110, "w"),
            ("mode", "Modus", 100, "center"),
            ("opts", "Optionen", 260, "w"),
        ])
        self.mount_tree.pack(fill="both", expand=True)
        for m in self.inventory.mounts:
            self.mount_tree.insert("", "end", values=(m.source, m.target, m.fs_type, "RO" if m.read_only else "RW", m.options))

        footer = ttk.Frame(self, style="Surface.TFrame", padding=(16, 8))
        footer.pack(fill="x")
        ttk.Label(
            footer,
            text="Nächster Schritt: einen Datenbereich bewusst auswählen und ausschließlich für Image/Recovery vorbereiten.",
            style="Muted.TLabel",
        ).pack(side="left")
