from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from kc_backup_program_registry import KCProgramDefinition, SourceKind


@dataclass(frozen=True)
class SourceCandidate:
    program_id: str
    source_id: str
    path: Path
    score: int
    reason: str


_PROGRAM_HINTS = {
    "pc-backup-vault": ("pc backup vault", "backup vault", "pc_backup_vault"),
    "kc-dp2": ("dp2", "dienstplan", "kc dp"),
    "kc-verwaltung": ("verwaltung", "kc verwaltung"),
    "kc-marktkasse": ("marktkasse", "kasse", "bilderkasse"),
    "kc-futura": ("futura", "academy"),
    "kc-tv-editor": ("tv-editor", "tv editor", "weihnachtsmarkt", "praesentation", "präsentation"),
    "kc-inventar": ("inventar", "inventur"),
    "kc-bilderrechner": ("bilderrechner", "bilder rechner"),
}
_SAFE_EXPORT_SUFFIXES = {".json", ".csv", ".xlsx", ".xls", ".zip", ".sql", ".dump"}
_RAW_DATABASE_SUFFIXES = {".db", ".sqlite", ".sqlite3"}
_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}


def _normal(text: str) -> str:
    return text.lower().replace("_", " ").replace("-", " ")


def is_safe_export_candidate(path: Path) -> bool:
    """Return True only for explicit export/container formats, never raw live DB files."""
    if not path.is_file():
        return False
    suffix = path.suffix.lower()
    if suffix in _RAW_DATABASE_SUFFIXES:
        return False
    if suffix in _SAFE_EXPORT_SUFFIXES:
        return True
    return path.name.lower().endswith(".sql.gz")


def _score_path(program: KCProgramDefinition, source, path: Path) -> tuple[int, str] | None:
    name = _normal(path.name)
    whole = _normal(str(path))
    hints = _PROGRAM_HINTS.get(program.program_id, ())
    score = 0
    reasons: list[str] = []
    for hint in hints:
        h = _normal(hint)
        if h in name:
            score += 60
            reasons.append(f"Name enthält '{hint}'")
        elif h in whole:
            score += 30
            reasons.append(f"Pfad enthält '{hint}'")
    source_words = [w for w in _normal(source.label).split() if len(w) >= 4]
    matches = [w for w in source_words if w in name]
    if matches:
        score += min(25, 8 * len(matches))
        reasons.append("passt zum Sicherungsbereich")

    if source.kind in {SourceKind.FOLDER, SourceKind.DOCUMENTS}:
        if not path.is_dir():
            return None
        score += 5
    else:
        if not is_safe_export_candidate(path):
            return None
        score += 10
        if any(token in name for token in ("export", "backup", "dump", "daten", "data")):
            score += 10
            reasons.append("typischer Exportname")

    if score < 30:
        return None
    return min(score, 100), "; ".join(reasons) or "Namens-/Typübereinstimmung"


def discover_candidates(
    root: str | Path,
    programs: Iterable[KCProgramDefinition],
    *,
    max_depth: int = 5,
    max_entries: int = 30_000,
    max_per_source: int = 8,
) -> list[SourceCandidate]:
    """Read-only, bounded source discovery below an explicitly selected root.

    The function never writes, follows no symlinks, never changes program
    configuration and never proposes raw .db/.sqlite files as exports.
    """
    base = Path(root).expanduser()
    if not base.exists() or not base.is_dir():
        raise ValueError("Suchordner existiert nicht oder ist kein Ordner")

    programs = tuple(programs)
    found: dict[tuple[str, str], list[SourceCandidate]] = {}
    seen = 0
    stack: list[tuple[Path, int]] = [(base, 0)]
    while stack and seen < max_entries:
        current, depth = stack.pop()
        try:
            entries = list(current.iterdir())
        except (OSError, PermissionError):
            continue
        for path in entries:
            seen += 1
            if seen > max_entries:
                break
            try:
                if path.is_symlink():
                    continue
                if path.is_dir() and path.name.lower() in _SKIP_DIRS:
                    continue
            except OSError:
                continue

            for program in programs:
                for source in program.sources:
                    result = _score_path(program, source, path)
                    if result is None:
                        continue
                    score, reason = result
                    key = (program.program_id, source.source_id)
                    found.setdefault(key, []).append(
                        SourceCandidate(program.program_id, source.source_id, path, score, reason)
                    )
            try:
                if depth < max_depth and path.is_dir():
                    stack.append((path, depth + 1))
            except OSError:
                pass

    result: list[SourceCandidate] = []
    for candidates in found.values():
        candidates.sort(key=lambda c: (-c.score, len(str(c.path)), str(c.path).lower()))
        result.extend(candidates[:max_per_source])
    return sorted(result, key=lambda c: (c.program_id, c.source_id, -c.score, str(c.path).lower()))


def candidates_for(candidates: Iterable[SourceCandidate], program_id: str, source_id: str) -> tuple[SourceCandidate, ...]:
    return tuple(c for c in candidates if c.program_id == program_id and c.source_id == source_id)
