from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Callable


class VerificationCancelled(RuntimeError):
    """Raised when a long-running read-only image verification is cancelled."""


@dataclass(frozen=True)
class ImageVerification:
    image_path: str
    size: int
    sha256: str
    verified_at: str


def verify_image(
    path: str | Path,
    chunk_size: int = 4 * 1024 * 1024,
    *,
    progress: Callable[[int, int], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> ImageVerification:
    """Verify a recovery image read-only with optional progress/cancel callbacks."""
    image = Path(path)
    if not image.is_file():
        raise FileNotFoundError(str(image))
    total = image.stat().st_size
    digest = hashlib.sha256()
    done = 0
    with image.open("rb") as handle:
        while True:
            if should_cancel and should_cancel():
                raise VerificationCancelled("Image-Verifikation wurde abgebrochen; das Image ist nicht als verifiziert markiert.")
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    return ImageVerification(str(image.resolve()), total, digest.hexdigest(), datetime.now(timezone.utc).isoformat())


def write_manifest(verification: ImageVerification, destination: str | Path | None = None) -> Path:
    image = Path(verification.image_path)
    target = Path(destination) if destination else image.with_suffix(image.suffix + ".verify.json")
    if target.resolve() == image.resolve():
        raise ValueError("Manifest darf die Image-Datei nicht überschreiben.")
    target.write_text(json.dumps(asdict(verification), indent=2, ensure_ascii=False), encoding="utf-8")
    return target


def manifest_matches_image(manifest_path: str | Path) -> bool:
    data = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    current = verify_image(data["image_path"])
    return current.size == int(data["size"]) and current.sha256 == data["sha256"]
