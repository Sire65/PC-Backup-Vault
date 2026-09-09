import argparse
import threading
from instance_lock import InstanceLock
from ui import App, SettingsWindow
from dashboard_window import DashboardWindow
import plan_runner as plan_runner_module
from plan_runner import run_plan
from kicc_backup_telemetry import start_backup_telemetry
from project_finder.main_integration import enable_project_finder
from project_finder.backup_handoff_v190 import enable_inventory_backup_handoff
from update_ui import enable_auto_update, schedule_startup_update_check
from scheduler import sync_all_tasks
import storage_v180 as storage_v180_module
from storage_v180 import apply_v180
from storage_v180_settings import apply_settings_v180
from transfer_monitor_v180 import apply_transfer_monitor
from assistant_v180 import apply_assistant_v180, BackupAssistant
import professional_v180 as professional_v180_module
from professional_integration_v180 import apply_professional_v180
from system_image_integration_v180 import apply_system_image_assistant
from all_tests_and_run_now_v180 import apply_all_tests_and_run_now_v180
from filesystem_progress_fix_v180 import apply_filesystem_progress_fix
from heartbeat_led_v180 import apply_heartbeat_led_v180
from ui_clarity_fix_v182 import apply_ui_clarity_fix_v182
from scheduler_release_v183 import apply_scheduler_release_v183
from release_polish_v183 import apply_release_polish_v183
from test_window_usability_v184 import apply_test_window_usability_v184
from restore_assistant_v186 import apply_restore_assistant_v186, RestoreAssistant, _file_group, _fmt_size
from restore_path_fix_v188 import apply_restore_path_fix_v188
from restore_filters_v189 import apply_restore_filters_v189
import cloud_targets_v191 as cloud_targets_module
import cloud_targets_ui_v191 as cloud_targets_ui_module
from cloud_targets_ui_v191 import apply_cloud_targets_v191
import hidrive_integration_v192 as hidrive_integration_module
from hidrive_integration_v192 import apply_hidrive_sftp_v192
from hidrive_tuev_fix_v1913 import apply_hidrive_tuev_fix_v1913, apply_explorer_labels_v1913
import hidrive_live_explorer_v1914 as hidrive_live_module
from hidrive_live_explorer_v1914 import apply_hidrive_live_explorer_v1914
from hidrive_live_safety_v1914 import apply_hidrive_live_safety_v1914
from hidrive_tree_explorer_v1915 import apply_hidrive_tree_explorer_v1915
from hidrive_tree_selection_safety_v1915 import apply_hidrive_tree_selection_safety_v1915
from hidrive_hidden_items_v1916 import apply_hidrive_hidden_items_v1916
from hidrive_account_list_fix_v1918 import apply_hidrive_account_list_fix_v1918
import context_progress_v1917 as context_progress_module
from context_progress_v1917 import apply_context_progress_v1917
from context_progress_safety_v1917 import apply_context_progress_safety_v1917
import storage_center_v1919 as storage_center_module
from storage_center_v1919 import apply_storage_center_v1919, StorageCenterWindow
from storage_center_exact_v1920 import apply_storage_center_exact_v1920
from storage_center_db_import_v1920 import apply_storage_center_db_import_v1920
from main_navigation_v1919 import apply_main_navigation_v1919
from test_runtime_fix_v1919 import apply_test_runtime_fix_v1919
from cloud_target_activation_v192 import apply_cloud_target_activation_v192
from unified_reporting_integration_v193 import apply_unified_reporting_v193
from backup_completion_ui_v1923 import apply_backup_completion_ui_v1923
from backup_workbench_v194 import apply_backup_workbench_v194, BackupWorkbench
from hotfix_v195 import apply_hotfix_v195
from backup_workbench_ui_v196 import apply_backup_workbench_ui_v196
from backup_target_selection_fix_v1921 import apply_backup_target_selection_fix_v1921
from backup_source_selection_safety_v1922 import apply_backup_source_selection_safety_v1922
from volume_label_ui_v1912 import apply_volume_labels_v1912
import job_archive_safe_v199  # patches archive upserts before the UI/refresh layer is imported
from job_archive_ui_v198 import apply_job_archive_v198, JobArchiveWindow, JobFilesWindow
from restore_explorer_v1911 import apply_restore_explorer_v1911
from vault_db import recent_jobs
from config_store import APP_VERSION
from kc_backup_bridge_v180 import start_bridge
import kc_communication as kc_communication_module
import ui as ui_module


enable_project_finder(App)
enable_auto_update(App)
apply_v180(App, ui_module)
apply_filesystem_progress_fix(storage_v180_module)
apply_settings_v180(SettingsWindow)
apply_transfer_monitor(App)
apply_assistant_v180(App)
enable_inventory_backup_handoff(App, BackupAssistant)
apply_cloud_targets_v191(SettingsWindow, BackupAssistant, storage_v180_module)
apply_hidrive_sftp_v192(App, cloud_targets_module, cloud_targets_ui_module, storage_v180_module, plan_runner_module)
apply_hidrive_tuev_fix_v1913(professional_v180_module)
apply_hidrive_live_safety_v1914(hidrive_live_module)
apply_hidrive_tree_explorer_v1915(hidrive_live_module)
apply_hidrive_tree_selection_safety_v1915(hidrive_live_module)
apply_hidrive_hidden_items_v1916(hidrive_live_module)
apply_hidrive_account_list_fix_v1918(hidrive_live_module)
apply_cloud_target_activation_v192(cloud_targets_ui_module)
apply_professional_v180(App, BackupAssistant, SettingsWindow, ui_module)
apply_unified_reporting_v193(App, storage_v180_module, hidrive_integration_module, ui_module)
apply_backup_completion_ui_v1923(App, ui_module)
apply_system_image_assistant(BackupAssistant)
apply_scheduler_release_v183(ui_module)
apply_all_tests_and_run_now_v180(App, BackupAssistant, ui_module)
apply_heartbeat_led_v180(App)
apply_ui_clarity_fix_v182(App, ui_module)
apply_release_polish_v183(App, DashboardWindow, ui_module)
apply_test_window_usability_v184(App)
apply_restore_assistant_v186(App, BackupAssistant)
apply_restore_path_fix_v188()
apply_restore_filters_v189(RestoreAssistant, _file_group, _fmt_size)
apply_backup_workbench_v194(App, storage_v180_module)
apply_hotfix_v195(App, BackupWorkbench, APP_VERSION)
apply_backup_workbench_ui_v196(BackupWorkbench)
apply_backup_target_selection_fix_v1921(BackupWorkbench)
apply_backup_source_selection_safety_v1922(BackupWorkbench)
apply_volume_labels_v1912(BackupWorkbench)
apply_job_archive_v198(App, RestoreAssistant, BackupWorkbench, recent_jobs)
apply_restore_explorer_v1911(JobArchiveWindow, RestoreAssistant)
apply_explorer_labels_v1913(App, JobArchiveWindow)
apply_hidrive_live_explorer_v1914(App)
apply_context_progress_v1917(App, hidrive_live_module, JobArchiveWindow, JobFilesWindow)
apply_context_progress_safety_v1917(context_progress_module, hidrive_live_module)
# 1.9.19 gathers existing backends and reorganizes the UI. 1.9.20 is then
# applied additively so every live target shows its actual database/filesystem
# root instead of relying on a configured label or default schema.
apply_storage_center_v1919(App)
apply_storage_center_exact_v1920(storage_center_module, StorageCenterWindow)
apply_storage_center_db_import_v1920(StorageCenterWindow)
apply_main_navigation_v1919(App, StorageCenterWindow)
apply_test_runtime_fix_v1919(App, SettingsWindow, ui_module, kc_communication_module)


def _show_already_running():
    try:
        import tkinter as tk
        from tkinter import messagebox
        root=tk.Tk(); root.withdraw()
        messagebox.showwarning("PC Backup Vault", "PC Backup Vault läuft bereits.\n\nEin zweiter Sicherungsprozess wurde aus Sicherheitsgründen nicht gestartet.", parent=root)
        root.destroy()
    except Exception:
        print("PC Backup Vault läuft bereits; zweiter Prozess blockiert.")


def main():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--run-plan")
    args, _ = ap.parse_known_args()
    lock = InstanceLock()
    if not lock.acquire():
        _show_already_running(); return 2
    try:
        if args.run_plan:
            run_plan(args.run_plan)
        else:
            app = App()
            app._instance_lock = lock
            def heartbeat_pulse(success=None):
                try:
                    app.after(0, lambda s=success: app.heartbeat_pulse_v180(s))
                except Exception:
                    pass
            app._kicc_backup_telemetry = start_backup_telemetry(app.store, app.active_dsn, heartbeat_pulse)
            def sync_scheduler_background():
                try:
                    sync_all_tasks(app.store)
                    app.after(0, app.refresh_system_status)
                except Exception:
                    pass
            threading.Thread(target=sync_scheduler_background, name="pbv-scheduler-sync", daemon=True).start()
            app._kc_backup_bridge = start_bridge(app)
            schedule_startup_update_check(app)
            app.mainloop()
            lock = None
        return 0
    finally:
        if lock is not None:
            lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
