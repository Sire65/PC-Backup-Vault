from __future__ import annotations

from dataclasses import dataclass

from .recovery_plan import RecoveryPlanState, RecoveryStage, STAGE_LABELS


@dataclass(frozen=True)
class RecoveryReadiness:
    stage: RecoveryStage
    label: str
    allowed: bool
    status: str
    reason: str


def readiness_snapshot(state: RecoveryPlanState) -> tuple[RecoveryReadiness, ...]:
    """Return deterministic UI/Leitstand readiness without executing recovery actions."""
    rows: list[RecoveryReadiness] = []
    next_stage = state.next_stage
    for stage in RecoveryStage:
        allowed = state.allowed(stage)
        if allowed and stage == next_stage:
            status, reason = "next", "Nächster freigegebener Schritt"
        elif allowed:
            status, reason = "ready", "Voraussetzungen erfüllt"
        else:
            status, reason = "blocked", "Voraussetzungen noch nicht erfüllt"
        rows.append(RecoveryReadiness(stage, STAGE_LABELS[stage], allowed, status, reason))
    return tuple(rows)


def overall_recovery_status(state: RecoveryPlanState) -> tuple[str, str]:
    if state.allowed(RecoveryStage.RECOVER):
        return "ok", "Recovery vorbereitet · separates Ziel bestätigt"
    if state.image_verified:
        return "warn", f"Image verifiziert · weiter mit {STAGE_LABELS[state.next_stage]}"
    if state.image_complete:
        return "warn", "Image vorhanden · Verifikation erforderlich"
    if state.source_identified:
        return "warn", f"Quelle erkannt · weiter mit {STAGE_LABELS[state.next_stage]}"
    return "off", "Noch keine Recovery-Quelle ausgewählt"
