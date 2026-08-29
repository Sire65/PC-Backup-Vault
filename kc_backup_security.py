from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class MaximumSecurityPolicy:
    """Fail-closed policy for future KC-wide backup and restore orchestration.

    The policy is intentionally independent from the existing backup engine. It
    can be adopted program by program without making any KC application depend
    on PC Backup Vault availability.
    """

    require_preflight: bool = True
    require_encryption: bool = True
    require_sha256: bool = True
    require_full_verify_after_backup: bool = True
    require_restore_test: bool = True
    require_separate_restore_target: bool = True
    forbid_restore_overwrite_by_default: bool = True
    require_explicit_restore_confirmation: bool = True
    require_recovery_material: bool = True
    minimum_independent_copies: int = 2
    recommended_independent_copies: int = 3
    immutable_copy_recommended: bool = True
    offline_copy_recommended: bool = True

    def as_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class PreflightResult:
    ok: bool
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    files: int = 0
    bytes_total: int = 0

    @property
    def status(self) -> str:
        if self.blockers:
            return "BLOCKED"
        return "WARN" if self.warnings else "SUCCESS"


@dataclass
class RestoreGuardResult:
    allowed: bool
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def preflight_paths(paths: Iterable[str | Path], *, target_ready: bool, recovery_material_ready: bool,
                    policy: MaximumSecurityPolicy | None = None) -> PreflightResult:
    policy = policy or MaximumSecurityPolicy()
    blockers: list[str] = []
    warnings: list[str] = []
    files = 0
    bytes_total = 0

    if not target_ready:
        blockers.append("Backup-Ziel ist nicht schreibbereit oder nicht erreichbar.")
    if policy.require_recovery_material and not recovery_material_ready:
        blockers.append("Recovery-Material ist nicht bestaetigt.")

    seen: set[str] = set()
    for raw in paths:
        p = Path(raw)
        if not p.exists():
            blockers.append(f"Quelle fehlt: {p}")
            continue
        candidates = [p] if p.is_file() else (x for x in p.rglob("*") if x.is_file())
        try:
            for f in candidates:
                try:
                    key = str(f.resolve()).lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    size = int(f.stat().st_size)
                    files += 1
                    bytes_total += max(0, size)
                except (OSError, PermissionError) as exc:
                    blockers.append(f"Datei nicht sicher lesbar: {f} ({exc})")
        except (OSError, PermissionError) as exc:
            blockers.append(f"Verzeichnis nicht sicher lesbar: {p} ({exc})")

    if files == 0 and not blockers:
        warnings.append("Keine Dateien fuer die Sicherung gefunden.")
    return PreflightResult(not blockers, blockers, warnings, files, bytes_total)


def guard_restore(*, source_verified: bool, recovery_material_ready: bool, target: str | Path,
                  protected_roots: Iterable[str | Path] = (), overwrite_requested: bool = False,
                  explicit_confirmation: bool = False, policy: MaximumSecurityPolicy | None = None) -> RestoreGuardResult:
    """Validate restore prerequisites without writing a single byte."""
    policy = policy or MaximumSecurityPolicy()
    blockers: list[str] = []
    warnings: list[str] = []
    target_path = Path(target)

    if not source_verified:
        blockers.append("Restore-Quelle ist nicht erfolgreich verifiziert.")
    if policy.require_recovery_material and not recovery_material_ready:
        blockers.append("Recovery-Material ist nicht bestaetigt.")
    if overwrite_requested and policy.forbid_restore_overwrite_by_default:
        blockers.append("Ueberschreiben ist in MAXIMUM-Sicherheitsstufe standardmaessig gesperrt.")
    if policy.require_explicit_restore_confirmation and not explicit_confirmation:
        blockers.append("Explizite Restore-Bestaetigung fehlt.")

    try:
        resolved_target = target_path.resolve(strict=False)
        for root in protected_roots:
            protected = Path(root).resolve(strict=False)
            if resolved_target == protected:
                blockers.append(f"Restore direkt in geschuetztes Originalziel ist gesperrt: {protected}")
                break
    except OSError as exc:
        blockers.append(f"Restore-Ziel kann nicht sicher aufgeloest werden: {exc}")

    target_has_content = False
    try:
        if target_path.is_dir():
            target_has_content = any(target_path.iterdir())
        elif target_path.exists():
            target_has_content = True
    except (OSError, PermissionError) as exc:
        blockers.append(f"Restore-Ziel kann nicht sicher gelesen werden: {exc}")

    if target_has_content:
        warnings.append("Restore-Ziel ist nicht leer; Wiederherstellung sollte in ein leeres Staging-Ziel erfolgen.")

    return RestoreGuardResult(not blockers, blockers, warnings)
