from __future__ import annotations

from windows_drive_inventory_v1924 import discover_drive_roots, drive_display, drive_inventory, drive_type_label


def apply_drive_inventory_v1924(WorkbenchClass, storage_center_exact_module, StorageCenterWindowClass):
    """Use one Windows drive inventory in every operator-facing drive overview.

    Raw drive roots remain the paths used by backup/explorer logic. Only the
    visible text is enriched with volume label/type/readiness information.
    """
    if getattr(WorkbenchClass, "_drive_inventory_v1924", False):
        return

    def load_source_browser(self):
        rows = drive_inventory()
        self._last_drive_inventory_v1924 = rows
        self.src_tree.delete(*self.src_tree.get_children())
        for row in rows:
            root = str(row.get("root") or "")
            iid = self.src_tree.insert("", "end", text=row.get("display") or root, values=(root,), open=False)
            self.src_tree.insert(iid, "end", text="…", values=("",))

    WorkbenchClass._load_source_browser = load_source_browser
    WorkbenchClass.refresh_drive_inventory_v1924 = load_source_browser
    WorkbenchClass._drive_inventory_v1924 = True

    # The Storage Center's "Dieser PC" loader reads this module-global helper at
    # runtime. Replacing only that helper preserves all existing copy/move/delete
    # safety logic while using the same complete inventory as the workbench.
    storage_center_exact_module._windows_drives = discover_drive_roots

    if getattr(StorageCenterWindowClass, "_drive_inventory_v1924", False):
        return

    original_insert = StorageCenterWindowClass._insert

    def _insert(self, parent, item, text, values, expandable=False):
        row = dict(item or {})
        shown_text = text
        shown_values = tuple(values or ())
        if row.get("backend") == "FILESYSTEM" and row.get("drive_root"):
            root = str(row.get("path") or row.get("name") or "")
            shown_text = f"💽 {drive_display(root)}"
            values_list = list(shown_values)
            if values_list:
                values_list[0] = drive_type_label(root)
            if len(values_list) >= 4:
                values_list[3] = root
            shown_values = tuple(values_list)
        return original_insert(self, parent, row, shown_text, shown_values, expandable=expandable)

    StorageCenterWindowClass._insert = _insert
    StorageCenterWindowClass._drive_inventory_v1924 = True
