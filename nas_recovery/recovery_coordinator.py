from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Callable

from .image_verification import verify_image, write_manifest
from .raid_analysis import inspect_image
from .recovery_plan import RecoveryStage
from .recovery_session import RecoverySession


class RecoveryCoordinator:
    """Stateful coordinator for the safe image-first recovery workflow.

    It never repairs or writes to an original disk. Operations after imaging work
    only on image files and a separate recovery destination. Device identities
    are explicit prerequisites; path differences alone never unlock recovery.
    """

    def __init__(self, session: RecoverySession | None = None):
        self.session = session or RecoverySession()
        self.last_inspection = None
        self.last_manifest: Path | None = None

    def identify_source(self, label: str, device: str = "", size: int = 0, device_id: str = "") -> RecoverySession:
        self.session = replace(self.session, source_label=str(label), source_device=str(device), source_size=int(size or 0), source_device_id=str(device_id or device), source_identified=True)
        return self.session

    def mark_source_assessed(self) -> RecoverySession:
        if not self.session.source_identified:
            raise RuntimeError("Quelle muss zuerst erkannt werden.")
        self.session = replace(self.session, source_assessed=True)
        return self.session

    def attach_completed_image(self, path: str | Path, device_id: str = "") -> RecoverySession:
        image = Path(path)
        if not image.is_file() or image.stat().st_size <= 0:
            raise ValueError("Nur eine vorhandene, nicht leere Image-Datei kann übernommen werden.")
        if not self.session.source_assessed:
            raise RuntimeError("Quellzustand muss vor der Image-Übernahme geprüft sein.")
        self.session = replace(self.session, image_path=str(image.resolve()), image_complete=True, image_verified=False, analysis_complete=False, image_sha256="", image_device_id=str(device_id or ""), recovery_target="", recovery_target_device_id="")
        return self.session

    def verify_attached_image(
        self,
        *,
        progress: Callable[[int, int], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> RecoverySession:
        if not self.session.image_complete or not self.session.image_path:
            raise RuntimeError("Kein abgeschlossenes Image vorhanden.")
        # Fail closed: session stays unverified until the full digest has completed.
        self.session = replace(self.session, image_verified=False, image_sha256="")
        evidence = verify_image(self.session.image_path, progress=progress, should_cancel=should_cancel)
        self.last_manifest = write_manifest(evidence)
        self.session = replace(self.session, image_sha256=evidence.sha256, image_verified=True)
        return self.session

    def analyze_verified_image(self):
        if not self.session.image_verified:
            raise RuntimeError("Image muss vor der Analyse verifiziert werden.")
        self.last_inspection = inspect_image(self.session.image_path)
        self.session = replace(self.session, analysis_complete=True)
        return self.last_inspection

    def select_recovery_target(self, path: str | Path, device_id: str = "") -> RecoverySession:
        target = Path(path).expanduser().resolve()
        image = Path(self.session.image_path).resolve() if self.session.image_path else None
        if image is not None and target == image:
            raise ValueError("Recovery-Ziel darf nicht die Image-Datei sein.")
        target.mkdir(parents=True, exist_ok=True)
        self.session = replace(self.session, recovery_target=str(target), recovery_target_device_id=str(device_id or ""))
        return self.session

    @property
    def ready_for_recovery_tool(self) -> bool:
        return self.session.plan_state().allowed(RecoveryStage.RECOVER)
