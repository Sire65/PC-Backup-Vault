"""NAS/RAID recovery module for PC Backup Vault.

The module is intentionally separated from backup and Git business logic. Original
NAS disks are treated as evidence sources and are read-only by policy.
"""

from .safety import RecoverySafetyPolicy, UnsafeRecoveryOperation
from .service import NasRecoveryService, PhysicalDisk, ReadTestResult
from .ui import NasRecoveryWindow

__all__ = [
    "RecoverySafetyPolicy",
    "UnsafeRecoveryOperation",
    "NasRecoveryService",
    "PhysicalDisk",
    "ReadTestResult",
    "NasRecoveryWindow",
]
