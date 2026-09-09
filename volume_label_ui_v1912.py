from __future__ import annotations

from tkinter import END, filedialog

from windows_volume_labels_v1912 import format_drive_display, format_location_display, is_drive_root


def apply_volume_labels_v1912(WorkbenchClass):
    """Add Windows volume labels to drive overviews without changing stored paths."""
    if getattr(WorkbenchClass, "_volume_labels_v1912", False):
        return

    original_load_source_browser = WorkbenchClass._load_source_browser
    original_refresh_sources = WorkbenchClass._refresh_sources

    def load_source_browser(self):
        original_load_source_browser(self)
        for iid in self.src_tree.get_children(""):
            values = self.src_tree.item(iid, "values")
            if not values:
                continue
            path = str(values[0] or "")
            if is_drive_root(path):
                self.src_tree.item(iid, text=format_drive_display(path))

    def refresh_sources(self):
        self.source_list.delete(0, "end")
        for path in self.selected_sources:
            shown = format_drive_display(path) if is_drive_root(path) else path
            self.source_list.insert("end", shown)

    WorkbenchClass._load_source_browser = load_source_browser
    WorkbenchClass._refresh_sources = refresh_sources
    WorkbenchClass._volume_labels_v1912 = True

    # Project Finder: keep the raw path in a separate column while showing a friendly label.
    try:
        from project_finder.ui_tab import ProjectFinderTab
    except Exception:
        return

    if getattr(ProjectFinderTab, "_volume_labels_v1912", False):
        return

    original_build = ProjectFinderTab._build

    def build(self):
        original_build(self)
        self.root_list.configure(columns=("name", "path"))
        self.root_list.heading("name", text="Laufwerk / Bezeichnung")
        self.root_list.heading("path", text="Pfad")
        self.root_list.column("name", width=300, anchor="w")
        self.root_list.column("path", width=600, anchor="w")

    def add_folder(self):
        path = filedialog.askdirectory(title="Laufwerk oder Verzeichnis für Inventur wählen")
        if path and path not in self.roots:
            self.roots.append(path)
            self.root_list.insert("", END, values=(format_location_display(path), path))

    def remove_selected_root(self):
        for iid in self.root_list.selection():
            values = self.root_list.item(iid, "values")
            path = str(values[1]) if len(values) > 1 else (str(values[0]) if values else "")
            if path in self.roots:
                self.roots.remove(path)
            self.root_list.delete(iid)

    ProjectFinderTab._build = build
    ProjectFinderTab.add_folder = add_folder
    ProjectFinderTab.remove_selected_root = remove_selected_root
    ProjectFinderTab._volume_labels_v1912 = True
