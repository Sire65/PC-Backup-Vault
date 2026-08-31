from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class ConsolidationFinding:
    code: str
    level: str
    message: str


@dataclass(frozen=True)
class ConsolidationResult:
    ready: bool
    findings: tuple[ConsolidationFinding, ...]


REQUIRED_FRAMEWORK_ADAPTERS = ("DesignCore", "WindowCore", "TableCore", "NavigationCore")
REQUIRED_PRIMARY_TASKS = ("secure", "check_disk", "recover", "restore", "projects", "system")
LONG_RUNNING_OPERATIONS = (
    "backup", "restore", "image", "image_verify", "disk_check", "nas_raid",
    "project_finder", "git_handoff", "import_export", "tuev",
)


def evaluate_final_consolidation(
    *,
    ci_green: bool,
    regression_green: bool,
    safety_green: bool,
    studio_rules_green: bool,
    framework_version_resolved: bool,
    framework_adapters: Mapping[str, bool],
    progress_coverage: Mapping[str, bool],
    primary_tasks: tuple[str, ...],
    main_untouched: bool,
) -> ConsolidationResult:
    """Fail-closed final consolidation gate; it never merges or mutates main."""
    findings: list[ConsolidationFinding] = []

    checks = (
        (ci_green, "CI", "Gesamt-CI ist nicht vollständig grün."),
        (regression_green, "REGRESSION", "Regression ist nicht vollständig grün."),
        (safety_green, "SAFETY", "Sicherheits-/Recovery-Prüfungen sind nicht vollständig grün."),
        (studio_rules_green, "STUDIO", "Framework-Studio/Vorgaben/Regeln sind nicht vollständig bestätigt."),
        (framework_version_resolved, "FRAMEWORK_VERSION", "Framework-Studio-Baseline ist noch nicht formal eindeutig geklärt."),
        (main_untouched, "MAIN", "main wurde vor der finalen Freigabe verändert."),
    )
    for ok, code, message in checks:
        if not ok:
            findings.append(ConsolidationFinding(code, "block", message))

    for name in REQUIRED_FRAMEWORK_ADAPTERS:
        if not framework_adapters.get(name, False):
            findings.append(ConsolidationFinding("FRAMEWORK_CORE", "block", f"{name} wird nicht über den vorhandenen Framework-Studio-Adapter genutzt."))

    for operation in LONG_RUNNING_OPERATIONS:
        if not progress_coverage.get(operation, False):
            findings.append(ConsolidationFinding("PROGRESS", "block", f"Langer Vorgang '{operation}' hat noch keine bestätigte sichtbare Fortschrittsführung."))

    if tuple(primary_tasks) != REQUIRED_PRIMARY_TASKS:
        findings.append(ConsolidationFinding("UX", "block", "Der einfache Leitstand entspricht nicht mehr den sechs freigegebenen Hauptaufgaben."))

    return ConsolidationResult(ready=not findings, findings=tuple(findings))
