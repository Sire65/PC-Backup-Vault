from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from kc_backup_program_registry import (
    KCProgramDefinition,
    KCProgramRegistry,
    SourceKind,
    resolve_program_scope,
)
from kc_backup_source_discovery import SourceCandidate


@dataclass(frozen=True)
class SourceAdoptionPreview:
    program_id: str
    source_id: str
    path: Path
    source_label: str
    source_ok: bool
    source_message: str
    program_ready_after: bool
    remaining_blockers: tuple[str, ...]
    warnings: tuple[str, ...]


def _validated_source_path(source, path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, "Gefundene Quelle existiert nicht mehr."
    if path.is_symlink():
        return False, "Symlinks werden nicht als KC-Sicherungsquelle übernommen."
    if source.kind in {SourceKind.FOLDER, SourceKind.DOCUMENTS}:
        if not path.is_dir():
            return False, "Für diesen Sicherungsbereich wird ein Ordner erwartet."
    else:
        if not path.is_file():
            return False, "Für diesen Sicherungsbereich wird eine Exportdatei erwartet."
    return True, "Quelle vorhanden und Quellentyp passend."


def prepare_candidate_adoption(
    registry: KCProgramRegistry,
    candidate: SourceCandidate,
) -> tuple[KCProgramRegistry, SourceAdoptionPreview]:
    """Validate one discovery suggestion and prepare a new registry in memory only.

    This function performs no persistence. The caller must explicitly save the
    returned registry after user confirmation.
    """
    program = registry.get(candidate.program_id)
    source = next((item for item in program.sources if item.source_id == candidate.source_id), None)
    if source is None:
        raise ValueError("Sicherungsbereich gehört nicht mehr zum aktuellen Programmregister.")

    path = Path(candidate.path)
    source_ok, source_message = _validated_source_path(source, path)
    if not source_ok:
        raise ValueError(source_message)

    updated_sources = tuple(
        replace(item, configured_path=str(path)) if item.source_id == source.source_id else item
        for item in program.sources
    )
    updated_program = replace(program, sources=updated_sources)
    updated_registry = KCProgramRegistry(
        updated_program if item.program_id == program.program_id else item
        for item in registry.all()
    )
    scope = resolve_program_scope(updated_program)
    preview = SourceAdoptionPreview(
        program_id=program.program_id,
        source_id=source.source_id,
        path=path,
        source_label=source.label,
        source_ok=True,
        source_message=source_message,
        program_ready_after=scope.ready,
        remaining_blockers=scope.blockers,
        warnings=scope.warnings,
    )
    return updated_registry, preview
