from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


MIB = 1024 * 1024


@dataclass(frozen=True)
class ImageInspection:
    path: Path
    size: int
    sha256_first_mib: str
    signatures: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class RaidImageSetAssessment:
    images: tuple[ImageInspection, ...]
    same_size: bool
    min_size: int
    max_size: int
    size_spread: int
    summary: str


def _detect_signatures(head: bytes) -> list[str]:
    """Detect common disk/container hints without modifying the image."""
    found: list[str] = []
    if len(head) >= 512 and head[510:512] == b"\x55\xaa":
        found.append("MBR")
    if b"EFI PART" in head[:65536]:
        found.append("GPT")
    if b"LABELONE" in head[:4 * MIB]:
        found.append("LVM2")
    if b"_BHRfS_M" in head[:4 * MIB]:
        found.append("Btrfs")
    if head[:4] == b"XFSB":
        found.append("XFS")
    if len(head) > 1082 and head[1080:1082] == b"\x53\xef":
        found.append("Ext2/3/4")
    if len(head) >= 11 and head[3:11] == b"NTFS    ":
        found.append("NTFS")
    if b"md" in head[:4096].lower() and b"raid" in head[:4096].lower():
        found.append("md/RAID-Hinweis")
    return found


def inspect_image(path: str | Path, read_bytes: int = 4 * MIB) -> ImageInspection:
    """Inspect an image strictly read-only; never opens physical drive paths."""
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise FileNotFoundError(f"Image nicht gefunden: {p}")
    if "physicaldrive" in str(p).lower():
        raise ValueError("PhysicalDrive-Pfade sind in der RAID-Imageanalyse nicht zulässig.")

    size = p.stat().st_size
    with p.open("rb") as handle:
        head = handle.read(max(MIB, int(read_bytes)))
    digest = hashlib.sha256(head[:MIB]).hexdigest()
    signatures = tuple(_detect_signatures(head))
    warnings: list[str] = []
    if size == 0:
        warnings.append("Image ist leer")
    if size < MIB:
        warnings.append("Image ist kleiner als 1 MiB")
    if not signatures:
        warnings.append("Keine einfache Signatur im gelesenen Kopfbereich erkannt")
    return ImageInspection(p, size, digest, signatures, tuple(warnings))


def assess_image_set(paths: Iterable[str | Path]) -> RaidImageSetAssessment:
    inspections = tuple(inspect_image(path) for path in paths)
    if not inspections:
        raise ValueError("Mindestens eine Image-Datei auswählen.")
    sizes = [item.size for item in inspections]
    min_size, max_size = min(sizes), max(sizes)
    spread = max_size - min_size
    same = spread == 0
    if len(inspections) == 1:
        summary = "Ein Image ausgewählt; für RAID-Rekonstruktion werden normalerweise mehrere Mitglied-Images benötigt."
    elif same:
        summary = f"{len(inspections)} Images mit identischer Größe erkannt. Das ist ein gutes, aber kein beweisendes RAID-Indiz."
    else:
        summary = (
            f"{len(inspections)} Images mit unterschiedlichen Größen erkannt. "
            "Reihenfolge, Datenoffset und tatsächliche RAID-Mitgliedschaft müssen vor einer Rekonstruktion geprüft werden."
        )
    return RaidImageSetAssessment(inspections, same, min_size, max_size, spread, summary)


def render_worksheet(assessment: RaidImageSetAssessment, raid_level: str = "Unbekannt") -> str:
    lines = [
        "RAID Recovery Arbeitsblatt – PC Backup Vault",
        f"Erstellt: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"Vermutetes RAID-Level: {raid_level or 'Unbekannt'}",
        f"Mitglied-Images: {len(assessment.images)}",
        f"Größen identisch: {'ja' if assessment.same_size else 'nein'}",
        f"Größenspanne: {assessment.size_spread} Bytes",
        "",
        "Images:",
    ]
    for index, item in enumerate(assessment.images, 1):
        lines.extend([
            f"{index}. {item.path}",
            f"   Größe: {item.size} Bytes",
            f"   SHA-256 erste 1 MiB: {item.sha256_first_mib}",
            f"   Signaturen: {', '.join(item.signatures) if item.signatures else 'keine einfache Signatur'}",
            f"   Hinweise: {', '.join(item.warnings) if item.warnings else 'keine'}",
        ])
    lines.extend([
        "",
        "In jeder Recovery-Engine dokumentieren:",
        "- Plattenreihenfolge",
        "- Stripe-/Chunk-Größe",
        "- Paritätsrotation / RAID-Layout",
        "- Datenoffset / Startsektor",
        "- Dateisystem / LVM / Btrfs / mdadm-Schichten",
        "- Anzahl gefundener Ordner und Dateien",
        "- Stichprobe großer und kleiner Dateien",
        "",
        "SICHERHEITSREGEL: Keine Rekonstruktion auf Originalplatten schreiben.",
        "Arbeitsgrundlage sind ausschließlich Images oder Kopien von Images.",
    ])
    return "\n".join(lines) + "\n"


def save_worksheet(path: str | Path, content: str) -> Path:
    """Write report atomically so a crash does not leave a half-written worksheet."""
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_text(content, encoding="utf-8")
    os.replace(temp, target)
    return target
