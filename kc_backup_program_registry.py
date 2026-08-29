from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Iterable


class SourceKind(str, Enum):
    FILES = "FILES"
    FOLDER = "FOLDER"
    LOCAL_EXPORT = "LOCAL_EXPORT"
    DATABASE_EXPORT = "DATABASE_EXPORT"
    DOCUMENTS = "DOCUMENTS"


class SourceRequirement(str, Enum):
    REQUIRED = "REQUIRED"
    OPTIONAL = "OPTIONAL"


@dataclass(frozen=True)
class BackupSourceDefinition:
    source_id: str
    label: str
    kind: SourceKind
    requirement: SourceRequirement = SourceRequirement.REQUIRED
    description: str = ""
    configured_path: str | None = None

    @property
    def configured(self) -> bool:
        return bool(str(self.configured_path or "").strip())


@dataclass(frozen=True)
class KCProgramDefinition:
    program_id: str
    display_name: str
    adapter_version: str = "1.0"
    sources: tuple[BackupSourceDefinition, ...] = field(default_factory=tuple)
    notes: str = ""

    def required_sources(self) -> tuple[BackupSourceDefinition, ...]:
        return tuple(s for s in self.sources if s.requirement == SourceRequirement.REQUIRED)

    def configured_sources(self) -> tuple[BackupSourceDefinition, ...]:
        return tuple(s for s in self.sources if s.configured)

    def missing_required_sources(self) -> tuple[BackupSourceDefinition, ...]:
        return tuple(s for s in self.required_sources() if not s.configured)

    @property
    def ready(self) -> bool:
        return not self.missing_required_sources()


@dataclass(frozen=True)
class ProgramBackupScope:
    program_id: str
    display_name: str
    paths: tuple[Path, ...]
    blockers: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ready(self) -> bool:
        return not self.blockers and bool(self.paths)


def resolve_program_scope(program: KCProgramDefinition) -> ProgramBackupScope:
    blockers: list[str] = []
    warnings: list[str] = []
    paths: list[Path] = []

    for source in program.sources:
        if not source.configured:
            if source.requirement == SourceRequirement.REQUIRED:
                blockers.append(f"Pflichtbereich nicht konfiguriert: {source.label}")
            else:
                warnings.append(f"Optionaler Bereich nicht konfiguriert: {source.label}")
            continue
        path = Path(str(source.configured_path))
        if not path.exists():
            message = f"Quelle nicht gefunden: {source.label} ({path})"
            if source.requirement == SourceRequirement.REQUIRED:
                blockers.append(message)
            else:
                warnings.append(message)
            continue
        paths.append(path)

    if not paths and not blockers:
        blockers.append("Keine sicherungsfähige Quelle konfiguriert.")

    return ProgramBackupScope(
        program_id=program.program_id,
        display_name=program.display_name,
        paths=tuple(paths),
        blockers=tuple(blockers),
        warnings=tuple(warnings),
    )


class KCProgramRegistry:
    def __init__(self, programs: Iterable[KCProgramDefinition] = ()):
        self._programs: dict[str, KCProgramDefinition] = {}
        for program in programs:
            self.register(program)

    def register(self, program: KCProgramDefinition) -> None:
        key = program.program_id.strip().lower()
        if not key:
            raise ValueError("program_id darf nicht leer sein")
        if key in self._programs:
            raise ValueError(f"Programm bereits registriert: {program.program_id}")
        self._programs[key] = program

    def get(self, program_id: str) -> KCProgramDefinition:
        key = program_id.strip().lower()
        if key not in self._programs:
            raise KeyError(program_id)
        return self._programs[key]

    def all(self) -> tuple[KCProgramDefinition, ...]:
        return tuple(sorted(self._programs.values(), key=lambda p: p.display_name.lower()))


# Templates only. Paths are intentionally unset until the real local/export
# locations have been inventoried and explicitly configured.
DEFAULT_KC_PROGRAMS = (
    KCProgramDefinition(
        program_id="kc-dp2",
        display_name="KC DP2",
        sources=(
            BackupSourceDefinition("program", "Programm-/Konfigurationsdaten", SourceKind.FOLDER),
            BackupSourceDefinition("local-data", "Lokale DP2-Daten / Export", SourceKind.LOCAL_EXPORT),
            BackupSourceDefinition("cloud-export", "Plan-/Cloud-Datenexport", SourceKind.DATABASE_EXPORT),
            BackupSourceDefinition("documents", "Dokumente", SourceKind.DOCUMENTS, SourceRequirement.OPTIONAL),
        ),
        notes="IndexedDB/Cloud-Daten werden nur über konsistenten Export/Snapshot angebunden, nicht durch Rohkopie laufender Datenbanken.",
    ),
    KCProgramDefinition(
        program_id="kc-verwaltung",
        display_name="KC Verwaltung",
        sources=(
            BackupSourceDefinition("program", "Programm-/Konfigurationsdaten", SourceKind.FOLDER),
            BackupSourceDefinition("local-data", "Lokale Verwaltungsdaten / Export", SourceKind.LOCAL_EXPORT),
            BackupSourceDefinition("cloud-export", "Datenbankexport", SourceKind.DATABASE_EXPORT),
            BackupSourceDefinition("documents", "Dokumente / Anhänge", SourceKind.DOCUMENTS, SourceRequirement.OPTIONAL),
        ),
    ),
    KCProgramDefinition(
        program_id="kc-marktkasse",
        display_name="KC Marktkasse",
        sources=(
            BackupSourceDefinition("manager", "PC-Manager / Konfiguration", SourceKind.FOLDER),
            BackupSourceDefinition("master-data", "Stammdaten-Export", SourceKind.LOCAL_EXPORT),
            BackupSourceDefinition("transaction-export", "Kassen-/Umsatzexport", SourceKind.LOCAL_EXPORT),
            BackupSourceDefinition("images", "Artikelbilder", SourceKind.FOLDER, SourceRequirement.OPTIONAL),
        ),
        notes="Kassen bleiben autonom. Backup Central liest nur vorbereitete, konsistente Exporte bzw. freigegebene Manager-Daten.",
    ),
    KCProgramDefinition(
        program_id="kc-futura",
        display_name="KC Futura",
        sources=(
            BackupSourceDefinition("program", "Programm-/Konfigurationsdaten", SourceKind.FOLDER),
            BackupSourceDefinition("local-data", "Lokale Schulungs-/Prüfungsdaten / Export", SourceKind.LOCAL_EXPORT),
            BackupSourceDefinition("cloud-export", "Academy-/Cloud-Datenexport", SourceKind.DATABASE_EXPORT),
            BackupSourceDefinition("documents", "Zertifikate / Dokumente", SourceKind.DOCUMENTS, SourceRequirement.OPTIONAL),
        ),
        notes="Cloud-Daten nur als konsistenter Export/Snapshot; keine Rohkopie einer laufenden Datenbank.",
    ),
    KCProgramDefinition(
        program_id="kc-tv-editor",
        display_name="KC TV-Editor",
        sources=(
            BackupSourceDefinition("program", "Programm-/Konfigurationsdaten", SourceKind.FOLDER),
            BackupSourceDefinition("projects", "Präsentations-/Projektdaten", SourceKind.FOLDER),
            BackupSourceDefinition("media", "Medien / Bilder / Vorlagen", SourceKind.FOLDER, SourceRequirement.OPTIONAL),
            BackupSourceDefinition("exports", "MP4-/PNG-/ZIP-Exporte", SourceKind.FOLDER, SourceRequirement.OPTIONAL),
        ),
        notes="Ausgabeexporte sind optional; entscheidend sind Programm-/Konfiguration und die bearbeitbaren Projektdaten.",
    ),
    KCProgramDefinition(
        program_id="kc-inventar",
        display_name="KC Inventar",
        sources=(
            BackupSourceDefinition("program", "Programm-/Konfigurationsdaten", SourceKind.FOLDER),
            BackupSourceDefinition("inventory-export", "Inventardaten / Export", SourceKind.LOCAL_EXPORT),
            BackupSourceDefinition("documents", "Protokolle / Ausdrucke", SourceKind.DOCUMENTS, SourceRequirement.OPTIONAL),
        ),
    ),
    KCProgramDefinition(
        program_id="kc-bilderrechner",
        display_name="KC Bilderrechner",
        sources=(
            BackupSourceDefinition("program", "Programm-/Konfigurationsdaten", SourceKind.FOLDER),
            BackupSourceDefinition("project-data", "Projekt-/Vorlagendaten", SourceKind.FOLDER),
            BackupSourceDefinition("assets", "Bilder / Grafiken", SourceKind.FOLDER, SourceRequirement.OPTIONAL),
            BackupSourceDefinition("exports", "Erzeugte Ausgaben", SourceKind.FOLDER, SourceRequirement.OPTIONAL),
        ),
        notes="Erzeugte Ausgaben sind optional; Quell-/Vorlagendaten bleiben der primäre Sicherungsumfang.",
    ),
)


def default_registry() -> KCProgramRegistry:
    return KCProgramRegistry(DEFAULT_KC_PROGRAMS)
