from __future__ import annotations

import posixpath


def _norm(path: str) -> str:
    return posixpath.normpath("/" + str(path or "").replace("\\", "/").lstrip("/"))


def _prune_nested_rows(rows: list[dict]) -> list[dict]:
    """
    If a selected directory already contains another selected entry, keep only
    the directory. This prevents duplicate delete/move/download operations in
    a hierarchical multi-selection.
    """
    ordered = sorted(
        [dict(row) for row in rows],
        key=lambda row: (_norm(row.get("path") or "").count("/"), _norm(row.get("path") or "").casefold()),
    )
    kept: list[dict] = []
    selected_dirs: list[str] = []
    for row in ordered:
        path = _norm(row.get("path") or "")
        if any(path.startswith(parent.rstrip("/") + "/") for parent in selected_dirs):
            continue
        kept.append(row)
        if bool(row.get("is_dir")):
            selected_dirs.append(path)
    return kept


def apply_hidrive_tree_selection_safety_v1915(live_module):
    if getattr(live_module, "_hidrive_tree_selection_safety_v1915", False):
        return
    Explorer = live_module.HiDriveLiveExplorer
    original_selected_rows = Explorer.selected_rows

    def selected_rows(self):
        return _prune_nested_rows(original_selected_rows(self))

    Explorer.selected_rows = selected_rows
    live_module._hidrive_tree_selection_safety_v1915 = True
