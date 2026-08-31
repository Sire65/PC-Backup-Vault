from __future__ import annotations

from dataclasses import dataclass


class UnsafeRecoveryOperation(RuntimeError):
    """Raised when an operation would violate the read-only recovery contract."""


@dataclass(frozen=True)
class RecoverySafetyPolicy:
    """Central safety contract derived from NAS Migration Studio v5.6.

    Original media may be inspected and read. Writes are only permitted to explicit
    destination files/directories that are not the original physical device.
    """

    blocked_terms: tuple[str, ...] = (
        "initialize",
        "initialisieren",
        "format",
        "formatieren",
        "repair",
        "reparieren",
        "fsck",
        "chkdsk /f",
        "chkdsk /r",
        "mdadm --assemble --force",
        "raid rebuild",
        "rebuild",
        "mount -o rw",
        "remount,rw",
        "diskpart clean",
        "diskpart convert",
        "set-disk -isreadonly $false",
        "write test",
        "schreibtest",
    )

    @staticmethod
    def is_physical_drive(value: str) -> bool:
        text = str(value or "").strip().lower().replace("/", "\\")
        return text.startswith("\\\\.\\physicaldrive")

    def assert_command_safe(self, command: str) -> None:
        normalized = " ".join(str(command or "").lower().split())
        for term in self.blocked_terms:
            if term in normalized:
                raise UnsafeRecoveryOperation(
                    f"Recovery-Sicherheitsmodus blockiert die Schreib-/Reparaturaktion: {term}"
                )

    def assert_original_disk_read_only(self, source: str, *, write: bool = False) -> None:
        if write and self.is_physical_drive(source):
            raise UnsafeRecoveryOperation(
                "Originale PhysicalDrive-Datenträger dürfen ausschließlich gelesen werden."
            )

    def assert_image_destination(self, source: str, destination: str) -> None:
        if not destination or self.is_physical_drive(destination):
            raise UnsafeRecoveryOperation(
                "Das Image-Ziel muss eine normale Datei auf einem anderen Datenträger sein."
            )
        if str(source).strip().lower() == str(destination).strip().lower():
            raise UnsafeRecoveryOperation("Quelle und Image-Ziel dürfen nicht identisch sein.")


DEFAULT_POLICY = RecoverySafetyPolicy()
