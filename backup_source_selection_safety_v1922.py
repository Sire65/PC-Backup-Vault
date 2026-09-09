from __future__ import annotations

import os
from pathlib import Path
from tkinter import filedialog, messagebox


def _norm(path: str) -> str:
    try:
        return os.path.normcase(os.path.abspath(str(path)))
    except Exception:
        return os.path.normcase(str(path))


def _same(a: str, b: str) -> bool:
    return _norm(a) == _norm(b)


def _is_dir(path: str) -> bool:
    try:
        return Path(path).is_dir()
    except Exception:
        return False


def _is_child(child: str, parent: str) -> bool:
    """True when child lies below parent (not equal)."""
    try:
        c = Path(_norm(child))
        p = Path(_norm(parent))
        if c == p:
            return False
        c.relative_to(p)
        return True
    except Exception:
        return False


def source_overlaps(sources: list[str]) -> list[tuple[str, str]]:
    """Return (parent-directory, child-source) overlaps."""
    rows: list[tuple[str, str]] = []
    for parent in sources:
        if not _is_dir(parent):
            continue
        for child in sources:
            if not _same(parent, child) and _is_child(child, parent):
                rows.append((parent, child))
    return rows


def merge_sources_safely(existing: list[str], additions: list[str]) -> tuple[list[str], list[str], list[str]]:
    """Merge source selections without silently widening backup scope.

    Returns (sources, removed_parents, blocked_broadening).

    Safety rules:
    - exact duplicates are ignored;
    - if a new child is selected beneath an already selected directory, the
      broad parent directory is removed and the narrower child is kept;
    - if a new directory would contain an already selected child, the broad
      directory is blocked (user must remove the child first to opt in);
    - if a single tree selection contains both parent and child, keep only the
      narrower child.
    """
    current = list(dict.fromkeys(str(x) for x in existing if str(x)))
    new = list(dict.fromkeys(str(x) for x in additions if str(x)))

    # A multi-selection may contain both a folder and one of its children.
    # Drop the broad folder from that new selection before merging.
    reduced: list[str] = []
    for item in new:
        if _is_dir(item) and any(_is_child(other, item) for other in new if not _same(other, item)):
            continue
        reduced.append(item)

    removed_parents: list[str] = []
    blocked: list[str] = []
    for item in reduced:
        if any(_same(item, old) for old in current):
            continue

        # Narrowing is safe: selecting a precise child replaces a previously
        # selected broad parent directory.
        parents = [old for old in current if _is_dir(old) and _is_child(item, old)]
        for parent in parents:
            current = [old for old in current if not _same(old, parent)]
            if parent not in removed_parents:
                removed_parents.append(parent)

        # Broadening is not silent: a parent directory must not be added over
        # existing precise selections unless the user first removes them.
        if _is_dir(item) and any(_is_child(old, item) for old in current):
            blocked.append(item)
            continue

        current.append(item)

    return current, removed_parents, blocked


def source_label(path: str) -> str:
    p = Path(path)
    try:
        if p.is_dir():
            return f"[ORDNER] {path}"
        if p.is_file():
            return f"[DATEI]  {path}"
    except Exception:
        pass
    return f"[QUELLE] {path}"


def apply_backup_source_selection_safety_v1922(WorkbenchClass):
    if getattr(WorkbenchClass, "_backup_source_selection_safety_v1922", False):
        return
    WorkbenchClass._backup_source_selection_safety_v1922 = True

    original_start = WorkbenchClass.start_backup

    def _safe_add(self, additions):
        merged, removed, blocked = merge_sources_safely(self.selected_sources, list(additions or []))
        self.selected_sources = merged
        self._refresh_sources()
        if removed:
            messagebox.showinfo(
                "Quellenauswahl eingegrenzt",
                "Zur Sicherheit wurde der übergeordnete Ordner aus der Auswahl entfernt, "
                "weil du darunter eine genauere Datei oder einen Unterordner gewählt hast.\n\n"
                "Entfernt: " + "\n".join(removed),
                parent=self,
            )
        if blocked:
            messagebox.showwarning(
                "Ordner nicht zusätzlich ausgewählt",
                "Der folgende Ordner würde die Sicherung deutlich erweitern und enthält bereits "
                "eine einzeln ausgewählte Quelle. Er wurde deshalb nicht automatisch hinzugefügt.\n\n"
                + "\n".join(blocked)
                + "\n\nWenn du bewusst den ganzen Ordner sichern willst, entferne zuerst die Einzelquelle und wähle dann den Ordner.",
                parent=self,
            )

    def add_source_selection(self):
        additions = []
        for iid in self.src_tree.selection():
            vals = self.src_tree.item(iid, "values")
            if vals and vals[0]:
                additions.append(str(vals[0]))
        _safe_add(self, additions)

    def pick_files(self):
        _safe_add(self, filedialog.askopenfilenames(parent=self, title="Quelldateien auswählen"))

    def pick_folder(self):
        path = filedialog.askdirectory(parent=self, title="Quellordner auswählen")
        if path:
            _safe_add(self, [path])

    def _refresh_sources(self):
        self.source_list.delete(0, "end")
        for path in self.selected_sources:
            self.source_list.insert("end", source_label(path))

    def start_backup(self):
        overlaps = source_overlaps(self.selected_sources)
        if overlaps:
            details = "\n".join(f"ORDNER: {parent}\n  enthält: {child}" for parent, child in overlaps[:8])
            messagebox.showwarning(
                "Quellenauswahl prüfen",
                "Backup wurde noch nicht gestartet. Ein ausgewählter Ordner enthält zusätzlich "
                "eine separat ausgewählte Datei oder einen Unterordner. Damit könnte unbeabsichtigt "
                "viel mehr gesichert werden als gewünscht.\n\n"
                + details
                + "\n\nBitte entferne entweder den Ordner oder die Einzelquelle und starte danach erneut.",
                parent=self,
            )
            return
        return original_start(self)

    WorkbenchClass.add_source_selection = add_source_selection
    WorkbenchClass.pick_files = pick_files
    WorkbenchClass.pick_folder = pick_folder
    WorkbenchClass._refresh_sources = _refresh_sources
    WorkbenchClass.start_backup = start_backup
