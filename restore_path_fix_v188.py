from __future__ import annotations

import ntpath
from pathlib import Path, PureWindowsPath

import restore_assistant_v186 as restore_module


def safe_relative_restore_path(original_path: str, file_name: str) -> Path:
    """Map an original Windows folder to a strictly relative path below a restore root.

    Drive roots and UNC anchors must never survive as absolute path components, otherwise
    pathlib on Windows can silently discard the selected restore root.
    """
    p = PureWindowsPath(str(original_path or ""))
    parts: list[str] = []

    drive = str(p.drive or "")
    if drive.startswith("\\\\"):
        unc_parts = [x for x in drive.strip("\\/").split("\\") if x]
        parts.extend(["UNC", *unc_parts])
    elif drive:
        label = drive.rstrip(":\\/")
        if label:
            parts.append(label)

    skip = {str(p.anchor or ""), str(p.drive or ""), str(p.root or ""), "\\", "/"}
    for raw in p.parts:
        raw = str(raw)
        if raw in skip:
            continue
        clean = raw.strip("\\/").replace(":", "")
        if not clean or clean in {".", ".."}:
            continue
        parts.append(clean)

    # Treat filenames as Windows names even when tests run on Linux. Path.name
    # alone does not strip backslash-separated traversal there.
    raw_name = str(file_name or "Datei").replace("/", "\\")
    safe_name = ntpath.basename(raw_name).strip("\\/")
    if not safe_name or safe_name in {".", ".."}:
        safe_name = "Datei"
    rel = Path(*parts) / safe_name
    if rel.is_absolute():
        raise ValueError("Interner Fehler: Wiederherstellungspfad ist nicht relativ.")
    return rel


def apply_restore_path_fix_v188() -> None:
    """Patch the 1.8.6/1.8.7 restore assistant without changing the restore engine."""
    restore_module._safe_rel = safe_relative_restore_path

    def _target_for(self, row):
        fid = str(row[0])
        meta = self.decoded[fid]
        name, folder = meta["name"], meta["path"]
        if self.destination_mode == "ORIGINAL":
            root = Path(folder)
            rel = Path(name)
            return root, rel, root / rel

        root = Path(self.destination)
        rel = safe_relative_restore_path(folder, name)
        final = root / rel
        # The path is constructed from relative components only. This explicit guard
        # catches future regressions before any restore write starts.
        try:
            final.relative_to(root)
        except ValueError as exc:
            raise ValueError("Wiederherstellungsziel liegt außerhalb des gewählten Zielordners.") from exc
        return root, rel, final

    restore_module.RestoreAssistant._target_for = _target_for
