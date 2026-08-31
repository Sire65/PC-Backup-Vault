from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .target_guard import recovery_target_is_safe


class RecoveryStage(str, Enum):
    DETECT = "detect"
    ASSESS = "assess"
    IMAGE = "image"
    VERIFY = "verify"
    ANALYZE = "analyze"
    RECOVER = "recover"


@dataclass(frozen=True)
class RecoveryPlanState:
    source_identified: bool = False
    source_assessed: bool = False
    image_path: str = ""
    image_complete: bool = False
    image_verified: bool = False
    analysis_complete: bool = False
    recovery_target: str = ""
    source_device_id: str = ""
    image_device_id: str = ""
    recovery_target_device_id: str = ""

    def allowed(self, stage: RecoveryStage) -> bool:
        """Prerequisite gate: unavailable recovery actions are not executable."""
        if stage is RecoveryStage.DETECT:
            return True
        if stage is RecoveryStage.ASSESS:
            return self.source_identified
        if stage is RecoveryStage.IMAGE:
            return self.source_identified and self.source_assessed
        if stage is RecoveryStage.VERIFY:
            return self.image_complete and bool(self.image_path)
        if stage is RecoveryStage.ANALYZE:
            return self.image_complete and self.image_verified and bool(self.image_path)
        if stage is RecoveryStage.RECOVER:
            return self.analysis_complete and self.image_verified and self.safe_target_selected
        return False

    @property
    def path_target_is_separate(self) -> bool:
        if not self.recovery_target or not self.image_path:
            return False
        try:
            target = Path(self.recovery_target).resolve()
            image = Path(self.image_path).resolve()
        except Exception:
            return False
        return target != image

    @property
    def safe_target_selected(self) -> bool:
        """Require both a different path and three known, distinct physical devices."""
        return self.path_target_is_separate and recovery_target_is_safe(
            self.source_device_id,
            self.image_device_id,
            self.recovery_target_device_id,
        )

    @property
    def next_stage(self) -> RecoveryStage:
        if not self.source_identified:
            return RecoveryStage.DETECT
        if not self.source_assessed:
            return RecoveryStage.ASSESS
        if not self.image_complete:
            return RecoveryStage.IMAGE
        if not self.image_verified:
            return RecoveryStage.VERIFY
        if not self.analysis_complete:
            return RecoveryStage.ANALYZE
        return RecoveryStage.RECOVER


STAGE_LABELS = {
    RecoveryStage.DETECT: "1. Quelle erkennen",
    RecoveryStage.ASSESS: "2. Zustand prüfen",
    RecoveryStage.IMAGE: "3. Sektor-Image erstellen",
    RecoveryStage.VERIFY: "4. Image verifizieren",
    RecoveryStage.ANALYZE: "5. Image analysieren",
    RecoveryStage.RECOVER: "6. Daten auf anderes Ziel retten",
}


def safety_summary(state: RecoveryPlanState) -> tuple[str, ...]:
    notes = ["Originalquelle nicht reparieren, formatieren oder initialisieren."]
    if not state.image_verified:
        notes.append("Analyse/Recovery bleibt bis zur Image-Verifikation gesperrt.")
    if not state.safe_target_selected:
        notes.append("Recovery benötigt ein separates physisches Ziel; Quelle, Image-Ziel und Rettungsziel müssen eindeutig verschieden sein.")
    return tuple(notes)
