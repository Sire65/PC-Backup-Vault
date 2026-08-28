"""Isolierter Vorschau-Start für den Project Finder.

Ändert weder Backup-Konfiguration noch B2-Verhalten. Die Vorschau startet nur den
neuen Inventar-/Analyse-Arbeitsbereich auf dem Entwicklungsbranch.
"""
import tkinter as tk
from tkinter import ttk

from project_finder.ui_workspace import ProjectInventoryWorkspace


def main():
    root = tk.Tk()
    root.title("PC Backup Vault – Projekt-Finder Vorschau")
    root.geometry("1280x800")
    root.minsize(980, 620)
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
