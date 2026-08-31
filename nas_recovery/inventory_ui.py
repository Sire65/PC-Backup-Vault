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
from .inventory import NasStorageInventory, classify_recovery_area, inventory_from_ssh_report


class NasInventoryWindow(tk.Toplevel):
    """Read-only view over storage information already collected by SSH diagnostics."""

    def __init__(self, parent, ssh_report):
        super().__init__(parent)
        self.report = ssh_report
        self.inventory: NasStorageInventory = inventory_from_ssh_report(ssh_report)
        self.title("PC Backup Vault – NAS Datenstruktur")
        self.configure(bg=TOKENS.bg)
        apply_design_adapter(self)
        normalize_window_geometry(self, 1180, 780, 920, 640)
        bind_window_escape(self, self.destroy)
        self._build()

    def _tree_with_scrollbars(self, parent, columns):
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        tree = ttk.Treeview(frame, height=12)
        configure_table(tree, columns)
        sy = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        sx = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        tree.grid(row=0, column=0, sticky="nsew")
        sy.grid(row=0, column=1, sticky="ns")
        sx.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        return tree

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
        ttk.Label(
            summary,
            text=(
                "Die Einstufung ist nur eine Heuristik. 'RW' zeigt ausschließlich den beobachteten Mount-Status auf dem NAS. "
                "PC Backup Vault erhält dadurch keinerlei Schreibfreigabe und arbeitet in diesem Bereich weiterhin read-only."
            ),
            style="Muted.TLabel",
            wraplength=1100,
            justify="left",
        ).pack(anchor="w", pady=(4, 0))

        notebook = ttk.Notebook(body)
        notebook.pack(fill="both", expand=True, pady=(10, 0))

        data_tab = ttk.Frame(notebook, padding=8)
        usage_tab = ttk.Frame(notebook, padding=8)
        mount_tab = ttk.Frame(notebook, padding=8)
        notebook.add(data_tab, text="Datenbereiche")
        notebook.add(usage_tab, text="Speicherbelegung")
        notebook.add(mount_tab, text="Mountpoints")

        self.data_tree = self._tree_with_scrollbars(data_tab, [
            ("path", "Pfad", 300, "w"),
            ("class", "Einstufung", 245, "w"),
            ("size", "Größe", 95, "e"),
            ("used", "Belegt", 95, "e"),
            ("free", "Frei", 95, "e"),
            ("percent", "Belegt %", 80, "center"),
            ("mode", "NAS-Mount", 110, "center"),
        ])

        usage_by_mount = {u.mountpoint: u for u in self.inventory.usage}
        mount_by_target = {m.target: m for m in self.inventory.mounts}
        all_paths = sorted(set(usage_by_mount) | set(mount_by_target))
        for path in all_paths:
            usage = usage_by_mount.get(path)
            mount = mount_by_target.get(path)
            assessment = classify_recovery_area(path, mount.fs_type if mount else "", mount.source if mount else (usage.filesystem if usage else ""))
            self.data_tree.insert("", "end", values=(
                path,
                assessment.label,
                usage.size if usage else "–",
                usage.used if usage else "–",
                usage.available if usage else "–",
                usage.percent if usage else "–",
                ("RO beobachtet" if mount and mount.read_only else "RW beobachtet" if mount else "unbekannt"),
            ))

        self.usage_tree = self._tree_with_scrollbars(usage_tab, [
            ("fs", "Dateisystem/Device", 260, "w"),
            ("size", "Größe", 100, "e"),
            ("used", "Belegt", 100, "e"),
            ("free", "Frei", 100, "e"),
            ("percent", "Belegt %", 90, "center"),
            ("mount", "Mountpoint", 360, "w"),
        ])
        for u in self.inventory.usage:
            self.usage_tree.insert("", "end", values=(u.filesystem, u.size, u.used, u.available, u.percent, u.mountpoint))

        self.mount_tree = self._tree_with_scrollbars(mount_tab, [
            ("source", "Quelle", 260, "w"),
            ("target", "Ziel", 330, "w"),
            ("type", "Typ", 110, "w"),
            ("mode", "NAS-Mount", 120, "center"),
            ("opts", "Optionen", 300, "w"),
        ])
        for m in self.inventory.mounts:
            self.mount_tree.insert("", "end", values=(m.source, m.target, m.fs_type, "RO beobachtet" if m.read_only else "RW beobachtet", m.options))

        footer = ttk.Frame(self, style="Surface.TFrame", padding=(16, 8))
        footer.pack(fill="x")
        ttk.Label(
            footer,
            text="System = nicht auswählen · Daten = Recovery-Kandidat · Unklar = zuerst prüfen. Keine Kategorie erlaubt Schreibzugriff auf das NAS.",
            style="Muted.TLabel",
        ).pack(side="left")
