from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path

from .recovery_plan import RecoveryPlanState


@dataclass(frozen=True)
class RecoverySession:
    source_label: str = ""
    source_device: str = ""
    source_size: int = 0
    image_path: str = ""
    image_sha256: str = ""
    recovery_target: str = ""
    source_identified: bool = False
    source_assessed: bool = False
    image_complete: bool = False
    image_verified: bool = False
    analysis_complete: bool = False

    def plan_state(self) -> RecoveryPlanState:
        return RecoveryPlanState(
            source_identified=self.source_identified,
            source_assessed=self.source_assessed,
            image_path=self.image_path,
            image_complete=self.image_complete,
            image_verified=self.image_verified,
            analysis_complete=self.analysis_complete,
            recovery_target=self.recovery_target,
        )

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8")
        return target

    @classmethod
    def load(cls, path: str | Path) -> "RecoverySession":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        allowed = cls.__dataclass_fields__.keys()
        return cls(**{k: data[k] for k in allowed if k in data})
