from __future__ import annotations

from unified_reporting_v193 import persist_local_job_report


def apply_unified_reporting_v193(AppClass, storage_module, hidrive_integration_module):
    """One consolidation layer for filesystem/NAS and HiDrive job results.

    It deliberately wraps existing production paths instead of replacing backup,
    encryption, SFTP, lifecycle or restore logic.
    """
    if getattr(AppClass, "_unified_reporting_v193", False):
        return

    original_fs = storage_module.filesystem_backup

    def filesystem_backup(app, paths, target, control=None, progress=None, plan_name=None):
        path_list = list(paths or [])
        result = original_fs(app, path_list, target, control=control, progress=progress, plan_name=plan_name)
        enriched = persist_local_job_report(app.store, result, path_list, target)
        result.clear(); result.update(enriched)
        return result

    storage_module.filesystem_backup = filesystem_backup

    # hidrive_integration_v192 imported this function into its module namespace.
    # Patching that namespace reaches manual, One-Touch and scheduler HiDrive paths
    # without touching the proven SFTP implementation itself.
    original_sftp = hidrive_integration_module.filesystem_backup_sftp

    def filesystem_backup_sftp(app, paths, target, control=None, progress=None, plan_name=None):
        path_list = list(paths or [])
        result = original_sftp(app, path_list, target, control=control, progress=progress, plan_name=plan_name)
        enriched = persist_local_job_report(app.store, result, path_list, target)
        result.clear(); result.update(enriched)
        return result

    hidrive_integration_module.filesystem_backup_sftp = filesystem_backup_sftp
    AppClass._unified_reporting_v193 = True
