from __future__ import annotations
from datetime import datetime
from config_store import ConfigStore
from backup_engine import collect_paths, backup_files, BackupCancelled
from selftest import run_restore_selftest
from verification import verify_job
from interrupted_recovery import save_plan_checkpoint, update_job_id, clear_checkpoint


def _log(store, text):
    try:
        path = store.path.parent / "scheduler.log"
        with path.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat(timespec='seconds')}  {text}\n")
    except Exception:
        pass


def _run_secondary_copy(store, plan, paths, key, progress=None, control=None):
    if not plan.get("secondary_copy_enabled", False):
        return {"status": "DISABLED"}
    secondary_id = plan.get("secondary_profile_id")
    if not secondary_id:
        return {"status": "WARN", "details": "Sekundärziel ist nicht ausgewählt."}
    if secondary_id == plan.get("profile_id"):
        return {"status": "WARN", "details": "Sekundärziel darf nicht mit dem Primärziel identisch sein."}
    profile = store.get_profile(secondary_id)
    if not profile:
        return {"status": "WARN", "details": "Sekundärziel wurde nicht gefunden."}
    dsn = store.get_dsn(profile["id"])
    if not dsn:
        return {"status": "WARN", "details": "Für das Sekundärziel fehlen Zugangsdaten im Windows-Anmeldetresor."}
    result = backup_files(
        dsn,
        key,
        profile,
        store.data,
        paths,
        progress,
        trigger_type="SECONDARY_COPY",
        plan_name=plan.get("name"),
        payload_target="NEON",
        object_store_config=store.get_b2_runtime_config(),
        control=control,
    )
    return {"status": result.get("status", "SUCCESS"), "result": result}


def run_plan(plan_id: str, progress=None, control=None, resume_from_job_id=None):
    store = ConfigStore()
    plan = store.get_plan(plan_id)
    if not plan:
        raise ValueError("One-Touch-Plan nicht gefunden.")
    if not plan.get("enabled", True):
        raise ValueError("One-Touch-Plan ist deaktiviert.")
    profile = store.get_profile(plan.get("profile_id"))
    if not profile:
        raise ValueError("Datenbank-Ziel des Plans wurde nicht gefunden.")
    dsn = store.get_dsn(profile["id"])
    if not dsn:
        raise ValueError("Für das Datenbank-Ziel fehlen Zugangsdaten im Windows-Anmeldetresor.")
    key = store.get_master_key()
    if not key:
        raise ValueError("Lokaler Verschlüsselungsschlüssel fehlt.")
    paths = collect_paths(plan.get("paths") or [], control=control)
    if not paths:
        raise ValueError("Die festgelegten Quellordner/-dateien sind nicht vorhanden oder leer.")
    trigger = "SCHEDULED" if plan.get("schedule_type") not in (None, "MANUAL") else "ONE_TOUCH"
    # A local encrypted checkpoint survives only an unexpected process/power loss.
    save_plan_checkpoint(key, plan_id, plan.get("paths") or [], "QUICK" if resume_from_job_id else "AUTO", plan.get("payload_target", "AUTO"), resume_from_job_id)
    def recovery_hook(event, payload):
        if event == "job_created": update_job_id(key, payload.get("job_id", ""))

    try:
        result = backup_files(
            dsn,
            key,
            profile,
            store.data,
            paths,
            progress,
            trigger_type=trigger,
            plan_name=plan.get("name"),
            payload_target=plan.get("payload_target", "AUTO"),
            object_store_config=store.get_b2_runtime_config(),
            control=control,
            backup_mode="QUICK" if resume_from_job_id else "AUTO",
            resume_from_job_id=resume_from_job_id,
            recovery_hook=recovery_hook,
        )

        if control is not None:
            control.check()
        verify_result = {"status": "DISABLED"}
        if store.data.get("auto_quick_verify_after_backup", True):
            try:
                vr = verify_job(
                    dsn, key, result.get("job_id"), mode="QUICK",
                    object_store_config=store.get_b2_runtime_config(), progress=progress,
                    control=control, app_version=store.data.get("app_version", "1.7.0"),
                )
                verify_result = vr.as_dict()
                verify_result["status"] = vr.result
            except BackupCancelled:
                raise
            except Exception as e:
                verify_result = {"status": "FAIL", "details": str(e)}

        if control is not None:
            control.check()
        selftest_result = {"status": "DISABLED"}
        if store.data.get("restore_selftest_after_backup", True):
            try:
                selftest_result = run_restore_selftest(
                    dsn,
                    key,
                    int(store.data.get("restore_selftest_max_kb", 256)),
                    object_store_config=store.get_b2_runtime_config(),
                )
            except Exception as e:
                selftest_result = {"status": "FAIL", "details": str(e)}

        if control is not None:
            control.check()
        try:
            secondary_result = _run_secondary_copy(store, plan, paths, key, progress, control=control)
        except BackupCancelled:
            raise
        except Exception as e:
            secondary_result = {"status": "FAIL", "details": str(e)}

        plan["last_run"] = datetime.now().isoformat(timespec="seconds")
        plan["last_secondary_status"] = secondary_result.get("status")
        if secondary_result.get("status") == "FAIL":
            plan["last_status"] = "PRIMARY_OK_SECONDARY_FAIL"
        elif verify_result.get("status") == "FAIL":
            plan["last_status"] = "PRIMARY_OK_VERIFY_FAIL"
        elif selftest_result.get("status") == "FAIL":
            plan["last_status"] = "PRIMARY_OK_SELFTEST_FAIL"
        else:
            plan["last_status"] = result.get("status", "SUCCESS")
        store.save()

        _log(
            store,
            f"PASS plan={plan.get('name')} files={result.get('files')} stored={result.get('stored_bytes')} "
            f"verify={verify_result.get('status')} selftest={selftest_result.get('status')} secondary={secondary_result.get('status')}",
        )
        result["verification"] = verify_result
        result["selftest"] = selftest_result
        result["secondary"] = secondary_result
        clear_checkpoint()
        return result
    except BackupCancelled:
        plan["last_run"] = datetime.now().isoformat(timespec="seconds")
        plan["last_status"] = "CANCELLED"
        store.save()
        _log(store, f"CANCELLED plan={plan.get('name')}")
        clear_checkpoint()
        raise
    except Exception as e:
        plan["last_run"] = datetime.now().isoformat(timespec="seconds")
        plan["last_status"] = "FAILED"
        store.save()
        _log(store, f"FAIL plan={plan.get('name')} error={e}")
        clear_checkpoint()
        raise
