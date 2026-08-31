from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class ReleaseGateResult:
    ready: bool
    status: str
    reasons: tuple[str, ...]


def evaluate_release_gate(*, ci_green: bool, required_modules: Mapping[str, bool], framework_version_resolved: bool, main_untouched: bool) -> ReleaseGateResult:
    """Fail-closed release gate for a candidate build; it never performs a merge."""
    reasons: list[str] = []
    if not ci_green:
        reasons.append("Gesamt-Regression/TÜV ist nicht grün.")
    missing = sorted(name for name, ready in required_modules.items() if not ready)
    if missing:
        reasons.append("Nicht vollständig verbunden: " + ", ".join(missing))
    if not framework_version_resolved:
        reasons.append("Framework-Studio-Versionsstand 1.38.38/1.38.39 ist noch nicht eindeutig aufgelöst.")
    if not main_untouched:
        reasons.append("Entwicklungsänderungen wurden bereits auf main übernommen; Freigabeprozess muss geprüft werden.")
    if reasons:
        return ReleaseGateResult(False, "blocked", tuple(reasons))
    return ReleaseGateResult(True, "candidate", ("Release-Kandidat kann zur manuellen Schlussabnahme vorgelegt werden.",))
