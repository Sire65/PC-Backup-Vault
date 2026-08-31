import argparse
from instance_lock import InstanceLock
from ui import App
from plan_runner import run_plan
from kicc_backup_telemetry import start_backup_telemetry
from project_finder.main_integration import enable_project_finder
from update_ui import enable_auto_update, schedule_startup_update_check
from cloud_failback import enable_cloud_failback
from provider_registry import enable_provider_registry
from nas_recovery.ui import NasRecoveryWindow, enable_nas_recovery
from nas_recovery.network_ui import NasNetworkWindow
from nas_recovery.raid_ui_integration import enable_raid_workspace
from nas_recovery.ssh_legacy_ui_integration import enable_legacy_ssh_probe
from nas_recovery.workflow_ui import enable_nas_workflow_ui
from control_center import enable_control_center
from nas_recovery.control_center_bridge import enable_nas_control_center_bridge


enable_project_finder(App)
enable_auto_update(App)
enable_cloud_failback(App)
enable_provider_registry(App)
enable_raid_workspace(NasRecoveryWindow)
enable_legacy_ssh_probe(NasNetworkWindow)
enable_nas_workflow_ui(NasRecoveryWindow)
enable_nas_recovery(App)
enable_nas_control_center_bridge()
enable_control_center(App)


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
            app._kicc_backup_telemetry = start_backup_telemetry(app.store, app.active_dsn)
            schedule_startup_update_check(app)
            app.mainloop()
            lock = None  # App owns/released below only if explicit; process exit releases regardless.
        return 0
    finally:
        if lock is not None:
            lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
