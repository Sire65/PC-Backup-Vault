from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .recovery_engines import RecoveryEngine, detect_recovery_engines, launch_engine
from .recovery_session import RecoverySession
from .recovery_plan import RecoveryStage


@dataclass(frozen=True)
class EngineHandoff:
    engine: RecoveryEngine
    image_path: str
    recovery_target: str
    ready: bool
    reason: str


def build_engine_handoffs(session: RecoverySession) -> tuple[EngineHandoff, ...]:
    """Prepare external-tool handoff without passing disk/image arguments automatically."""
    plan = session.plan_state()
    allowed = plan.allowed(RecoveryStage.RECOVER)
    image_ok = bool(session.image_path) and Path(session.image_path).is_file() and "physicaldrive" not in session.image_path.lower()
    target_ok = bool(session.recovery_target) and Path(session.recovery_target).exists()
    result = []
    for engine in detect_recovery_engines():
        ready = bool(allowed and image_ok and target_ok and engine.installed)
        if not allowed:
            reason = "Recovery-Ablauf noch nicht freigegeben."
        elif not image_ok:
            reason = "Verifiziertes Image fehlt oder ist ungültig."
        elif not target_ok:
            reason = "Separates Recovery-Ziel fehlt."
        elif not engine.installed:
            reason = "Recovery-Engine nicht installiert."
        else:
            reason = "Bereit. Image und Ziel werden angezeigt, aber nicht automatisch an das Fremdprogramm übergeben."
        result.append(EngineHandoff(engine, session.image_path, session.recovery_target, ready, reason))
    return tuple(result)


def launch_handoff(handoff: EngineHandoff) -> None:
    if not handoff.ready:
        raise RuntimeError(handoff.reason)
    if "physicaldrive" in handoff.image_path.lower():
        raise ValueError("PhysicalDrive darf niemals an eine Recovery-Engine übergeben werden.")
    launch_engine(handoff.engine)
