from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DeviceIdentity:
    """Stable-enough device identity supplied by a read-only resolver."""
    device_id: str
    label: str = ""

    @property
    def known(self) -> bool:
        return bool(self.device_id.strip())


def devices_are_distinct(*identities: str) -> bool:
    """Require every supplied device identity to be known and physically distinct.

    The function is deliberately pure. Platform-specific discovery may populate
    these IDs, but this gate itself never probes, mounts, formats or writes media.
    """
    normalized = [str(value or "").strip().lower() for value in identities]
    if not normalized or any(not value for value in normalized):
        return False
    return len(set(normalized)) == len(normalized)


def recovery_target_is_safe(source_device_id: str, image_device_id: str, recovery_target_device_id: str) -> bool:
    """Recovery requires a third known device, distinct from source and image target."""
    return devices_are_distinct(source_device_id, image_device_id, recovery_target_device_id)
