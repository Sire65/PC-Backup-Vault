from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path

from .recovery_session import RecoverySession


def build_recovery_audit(session: RecoverySession) -> dict:
    """Create a non-secret recovery evidence record without touching source media."""
    state = session.plan_state()
    return {
        "schema": "pc-backup-vault.recovery-audit.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "session": asdict(session),
        "readiness": {
            "next_stage": state.next_stage.value,
            "safe_target_selected": state.safe_target_selected,
            "source_identified": session.source_identified,
            "source_assessed": session.source_assessed,
            "image_complete": session.image_complete,
            "image_verified": session.image_verified,
            "analysis_complete": session.analysis_complete,
        },
        "safety": {
            "original_write_performed": False,
            "format_or_initialize_performed": False,
            "filesystem_repair_performed": False,
            "raid_force_assemble_performed": False,
        },
    }


def save_recovery_audit(session: RecoverySession, destination: str | Path) -> Path:
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_text(json.dumps(build_recovery_audit(session), indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(target)
    return target
