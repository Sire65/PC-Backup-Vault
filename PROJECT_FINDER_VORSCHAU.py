"""Produktiver, isolierter Start für die PC Backup Vault Inventur.

Der Runner scannt/vergleicht und erzeugt Empfehlungen. Bestehende Backup-Konfiguration,
Backup-Engine und B2-Verhalten werden nicht verändert. Endgültiges Löschen erfolgt nie
automatisch; sichere Dubletten können nur nach Benutzerfreigabe in Quarantäne verschoben werden.
"""
import tkinter as tk
from tkinter import ttk

from project_finder.ui_workspace import ProjectInventoryWorkspace


def main():
    root = tk.Tk()
    root.title("PC Backup Vault – Produktive Inventur")
    root.geometry("1380x860")
    root.minsize(1024, 680)
    style = ttk.Style(root)
    try:
        style.theme_use("vista")
    except tk.TclError:
        pass
    workspace = ProjectInventoryWorkspace(root)
    workspace.pack(fill="both", expand=True)
    root.mainloop()


if __name__ == "__main__":
    main()
