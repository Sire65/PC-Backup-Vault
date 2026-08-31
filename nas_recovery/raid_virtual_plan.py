from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .raid_analysis import assess_image_set


SUPPORTED_LEVELS = {"RAID0", "RAID1", "RAID5", "RAID6", "RAID10", "UNKNOWN"}


@dataclass(frozen=True)
class VirtualRaidPlan:
    image_paths: tuple[str, ...]
    raid_level: str
    member_count: int
    same_size: bool
    ready_for_external_analysis: bool
    warnings: tuple[str, ...]


def build_virtual_raid_plan(paths: Iterable[str | Path], raid_level: str = "UNKNOWN") -> VirtualRaidPlan:
    """Create a planning object only from image files; never from PhysicalDrive paths."""
    normalized = []
    for raw in paths:
        text = str(raw)
        if "physicaldrive" in text.lower():
            raise ValueError("Virtuelle RAID-Planung akzeptiert ausschließlich Image-Dateien.")
        normalized.append(str(Path(raw).expanduser().resolve()))
    level = str(raid_level or "UNKNOWN").upper().replace(" ", "")
    if level not in SUPPORTED_LEVELS:
        raise ValueError(f"Nicht unterstütztes RAID-Level: {raid_level}")
    assessment = assess_image_set(normalized)
    warnings = []
    if len(assessment.images) < 2:
        warnings.append("Für eine RAID-Rekonstruktion sind normalerweise mehrere Mitglied-Images erforderlich.")
    if not assessment.same_size:
        warnings.append("Image-Größen unterscheiden sich; Reihenfolge, Offset und Mitgliedschaft manuell prüfen.")
    minimum = {"RAID0": 2, "RAID1": 2, "RAID5": 3, "RAID6": 4, "RAID10": 4}.get(level, 2)
    if level != "UNKNOWN" and len(assessment.images) < minimum:
        warnings.append(f"{level} benötigt typischerweise mindestens {minimum} Mitglieder.")
    ready = len(assessment.images) >= 2 and (level == "UNKNOWN" or len(assessment.images) >= minimum)
    return VirtualRaidPlan(tuple(str(x.path) for x in assessment.images), level, len(assessment.images), assessment.same_size, ready, tuple(warnings))
