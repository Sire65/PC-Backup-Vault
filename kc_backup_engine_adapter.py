from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

from kc_backup_scheduler import OneTouchBackupPlan, ScheduleAction
from kc_backup_security import preflight_paths


@dataclass(frozen=True)
class PreparedBackupExecution:
    allowed: bool
    action: ScheduleAction
    program_id: str
    paths: tuple[Path, ...]
    blockers: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)
    backup_mode: str = "AUTO"
    payload_target: str = "AUTO"
    trigger_type: str = "SCHEDULER"
    plan_name: str = "KC Backup Central"


def prepare_backup_execution(
    *,
    program_id: str,
    action: ScheduleAction,
    paths: Iterable[str | Path],
    target_ready: bool,
    recovery_material_ready: bool,
    backup_mode: str = "AUTO",
    payload_target: str = "AUTO",
    trigger_type: str = "SCHEDULER",
    plan_name: str = "KC Backup Central",
) -> PreparedBackupExecution:
    """Prepare an execution without calling the productive backup engine.

    This adapter is intentionally fail-closed. It validates the source set via
    the KC preflight layer and merely returns immutable execution metadata.
    """
    action = action if isinstance(action, ScheduleAction) else ScheduleAction(action)
    normalized_paths = tuple(Path(p) for p in paths)

    if action != ScheduleAction.BACKUP:
        return PreparedBackupExecution(
            allowed=False,
            action=action,
            program_id=program_id,
            paths=normalized_paths,
            blockers=("Dieser Adapter startet ausschließlich BACKUP-Jobs. VERIFY und RESTORE_TEST benötigen eigene Adapter.",),
            backup_mode=backup_mode,
            payload_target=payload_target,
            trigger_type=trigger_type,
            plan_name=plan_name,
        )

    result = preflight_paths(
        normalized_paths,
        target_ready=target_ready,
        recovery_material_ready=recovery_material_ready,
    )
    return PreparedBackupExecution(
        allowed=result.ok,
        action=action,
        program_id=program_id,
        paths=normalized_paths,
        blockers=tuple(result.blockers),
        warnings=tuple(result.warnings),
        backup_mode=backup_mode,
        payload_target=payload_target,
        trigger_type=trigger_type,
        plan_name=plan_name,
    )


def prepare_one_touch_backup(
    *,
    program_id: str,
    paths: Iterable[str | Path],
    target_ready: bool,
    recovery_material_ready: bool,
    backup_mode: str = "AUTO",
    payload_target: str = "AUTO",
) -> PreparedBackupExecution:
    plan = OneTouchBackupPlan(program_id=program_id)
    return prepare_backup_execution(
        program_id=plan.program_id,
        action=ScheduleAction.BACKUP,
        paths=paths,
        target_ready=target_ready,
        recovery_material_ready=recovery_material_ready,
        backup_mode=backup_mode,
        payload_target=payload_target,
        trigger_type="ONE_TOUCH",
        plan_name=plan.visible_summary(),
    )


def execute_prepared_backup(
    prepared: PreparedBackupExecution,
    *,
    engine: Callable[..., object],
    dsn: str,
    key_b64: str,
    profile: dict,
    config: dict,
    object_store_config: dict | None = None,
    progress=None,
    control=None,
) -> object:
    """Invoke the existing engine only for an already allowed prepared BACKUP.

    Engine injection keeps this module testable and avoids importing or
    modifying backup_engine internals. No restore operation can pass here.
    """
    if not prepared.allowed:
        raise RuntimeError("Backup ist durch den KC-Probelauf blockiert: " + "; ".join(prepared.blockers))
    if prepared.action != ScheduleAction.BACKUP:
        raise RuntimeError("Nur vorbereitete BACKUP-Jobs dürfen an die bestehende Backup-Engine übergeben werden.")

    return engine(
        dsn,
        key_b64,
        profile,
        config,
        list(prepared.paths),
        progress=progress,
        trigger_type=prepared.trigger_type,
        plan_name=prepared.plan_name,
        backup_mode=prepared.backup_mode,
        payload_target=prepared.payload_target,
        object_store_config=object_store_config,
        control=control,
    )
