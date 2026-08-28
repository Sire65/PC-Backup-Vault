from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from .local_baseline_compare import sha256_file


@dataclass
class FullTreeResult:
    root: str
    state: str
    reference_file_count: int
    local_file_count: int
    missing: list[str]
    extra: list[str]
    changed: list[str]
    same: list[str]
    full_tree_verified: bool
    reason: str


def _normalize_manifest(reference_hashes: dict[str, str]) -> dict[str, str]:
    return {
        str(Path(path).as_posix()).lstrip('./'): str(digest).lower().strip()
        for path, digest in reference_hashes.items()
        if str(path).strip() and str(digest).strip()
    }


def compare_full_tree(root: str | Path, reference_hashes: dict[str, str]) -> FullTreeResult:
    """Compare every source path and SHA256 against an authoritative manifest.

    Equality requires the exact same relative path set and matching content hashes.
    The function is read-only and intentionally treats unreadable files as changed.
    """
    p = Path(root)
    reference = _normalize_manifest(reference_hashes)
    local_paths: set[str] = set()
    try:
        for entry in p.rglob('*'):
            if entry.is_file():
                local_paths.add(entry.relative_to(p).as_posix())
    except OSError:
        pass

    ref_paths = set(reference)
    missing = sorted(ref_paths - local_paths)
    extra = sorted(local_paths - ref_paths)
    changed: list[str] = []
    same: list[str] = []

    for rel in sorted(ref_paths & local_paths):
        try:
            actual = sha256_file(p / Path(rel))
        except OSError:
            changed.append(rel)
            continue
        if actual.lower() == reference[rel]:
            same.append(rel)
        else:
            changed.append(rel)

    verified = bool(reference) and not missing and not extra and not changed and len(same) == len(reference)
    if not reference:
        state = 'NO_REFERENCE_MANIFEST'
        reason = 'Kein vollständiges Referenzmanifest vorhanden; Identitätsnachweis ist unmöglich.'
    elif missing:
        state = 'MISSING_FILES'
        reason = f'{len(missing)} Referenzdateien fehlen im lokalen Quellstand.'
    elif extra:
        state = 'EXTRA_FILES'
        reason = f'{len(extra)} zusätzliche lokale Dateien verhindern einen exakten Referenzabgleich.'
    elif changed:
        state = 'CONTENT_DIFFERS'
        reason = f'{len(changed)} Dateien unterscheiden sich inhaltlich von der Referenz.'
    elif verified:
        state = 'EXACT_MATCH'
        reason = 'Alle relativen Pfade und SHA256-Inhalte stimmen exakt mit dem Referenzmanifest überein.'
    else:
        state = 'COMPARE_REQUIRED'
        reason = 'Vollständiger Identitätsnachweis nicht abgeschlossen.'

    return FullTreeResult(
        root=str(p),
        state=state,
        reference_file_count=len(reference),
        local_file_count=len(local_paths),
        missing=missing,
        extra=extra,
        changed=changed,
        same=same,
        full_tree_verified=verified,
        reason=reason,
    )


def as_report(result: FullTreeResult) -> dict:
    row = asdict(result)
    row['schema'] = 'pc-backup-vault.full-tree-compare.v1'
    row['read_only'] = True
    row['safe_to_merge_by_itself'] = False
    return row
