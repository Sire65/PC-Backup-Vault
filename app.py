import argparse
from instance_lock import InstanceLock
from ui import App, SettingsWindow
from plan_runner import run_plan
from kicc_backup_telemetry import start_backup_telemetry
from project_finder.main_integration import enable_project_finder
from update_ui import enable_auto_update, schedule_startup_update_check
import storage_v180 as storage_v180_module
from storage_v180 import apply_v180
from storage_v180_settings import apply_settings_v180
from transfer_monitor_v180 import apply_transfer_monitor
from assistant_v180 import apply_assistant_v180, BackupAssistant
from professional_integration_v180 import apply_professional_v180
from system_image_integration_v180 import apply_system_image_assistant
from all_tests_and_run_now_v180 import apply_all_tests_and_run_now_v180
from filesystem_progress_fix_v180 import apply_filesystem_progress_fix
from heartbeat_led_v180 import apply_heartbeat_led_v180
from ui_clarity_fix_v182 import apply_ui_clarity_fix_v182
from kc_backup_bridge_v180 import start_bridge
import ui as ui_module


enable_project_finder(App)
enable_auto_update(App)
apply_v180(App, ui_module)
apply_filesystem_progress_fix(storage_v180_module)
apply_settings_v180(SettingsWindow)
apply_transfer_monitor(App)
apply_assistant_v180(App)
apply_professional_v180(App, BackupAssistant, SettingsWindow, ui_module)
apply_system_image_assistant(BackupAssistant)
apply_all_tests_and_run_now_v180(App, BackupAssistant, ui_module)
apply_heartbeat_led_v180(App)
apply_ui_clarity_fix_v182(App, ui_module)


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
            # KICC telemetry is observation-only and never participates in backup/restore decisions.
            def heartbeat_pulse(success=None):
                try:
                    app.after(0, lambda s=success: app.heartbeat_pulse_v180(s))
                except Exception:
                    pass
            app._kicc_backup_telemetry = start_backup_telemetry(app.store, app.active_dsn, heartbeat_pulse)
            # KC programs submit backup requests to the local durable bridge. The bridge contains no secrets.
            app._kc_backup_bridge = start_bridge(app)
            schedule_startup_update_check(app)
            app.mainloop()
            lock = None  # App owns/released below only if explicit; process exit releases regardless.
        return 0
    finally:
        if lock is not None:
            lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
