from __future__ import annotations

from scheduler import task_diagnostic


def apply_scheduler_release_v183(ui_module):
    """Append one read-only scheduler release check for every configured plan.

    The existing TÜV function remains authoritative; this wrapper only adds detailed
    scheduler diagnostics. Because the consolidated test calls ui_module.run_tuev at
    runtime, the per-plan checks automatically appear in 'Alle Tests'.
    """
    original = ui_module.run_tuev
    if getattr(original, "_pbv_scheduler_release_v183", False):
        return

    def run_tuev_with_scheduler(dsn, has_master_key, recovery_key_exported, profile, config):
        checks = list(original(dsn, has_master_key, recovery_key_exported, profile, config) or [])
        plans = list((config or {}).get("plans", []) or [])
        if not plans:
            checks.append(("SCH-000", "Scheduler-Pläne", "PASS", "Keine automatischen Backup-Pläne konfiguriert"))
            return checks
        for idx, plan in enumerate(plans, start=1):
            try:
                result, detail = task_diagnostic(plan)
            except Exception as exc:
                result, detail = "WARN", f"{plan.get('name') or 'Backup-Plan'}: {exc}"
            checks.append((f"SCH-{idx:03d}", "Scheduler-Plan", result, detail))
        return checks

    run_tuev_with_scheduler._pbv_scheduler_release_v183 = True
    ui_module.run_tuev = run_tuev_with_scheduler
