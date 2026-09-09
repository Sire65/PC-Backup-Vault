import re
import unittest
from pathlib import Path

from config_store import APP_VERSION


ROOT = Path(__file__).resolve().parents[1]


class DeepConsolidationV1924Tests(unittest.TestCase):
    def test_patch_order_preserves_transport_reporting_and_tuev_chain(self):
        app = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertLess(app.index("apply_hidrive_sftp_v192("), app.index("apply_hidrive_tuev_fix_v1913("))
        self.assertLess(app.index("apply_hidrive_tuev_fix_v1913("), app.index("apply_drive_inventory_tuev_v1924("))
        self.assertLess(app.index("apply_drive_inventory_tuev_v1924("), app.index("apply_professional_v180("))
        self.assertLess(app.index("apply_unified_reporting_v193("), app.index("apply_backup_completion_ui_v1923("))
        self.assertLess(app.index("apply_backup_workbench_v194("), app.index("apply_backup_workbench_ui_v196("))
        self.assertLess(app.index("apply_backup_workbench_ui_v196("), app.index("apply_backup_target_selection_fix_v1921("))
        self.assertLess(app.index("apply_volume_labels_v1912("), app.index("apply_drive_inventory_v1924("))
        self.assertLess(app.index("apply_storage_center_exact_v1920("), app.index("apply_drive_inventory_v1924("))

    def test_new_patches_are_applied_exactly_once(self):
        app = (ROOT / "app.py").read_text(encoding="utf-8")
        for name in (
            "apply_drive_inventory_tuev_v1924",
            "apply_drive_inventory_v1924",
            "apply_backup_completion_ui_v1923",
            "apply_backup_target_selection_fix_v1921",
        ):
            calls = re.findall(rf"^{re.escape(name)}\(", app, flags=re.MULTILINE)
            self.assertEqual(len(calls), 1, name)

    def test_installer_version_matches_program(self):
        iss = (ROOT / "installer" / "PC_Backup_Vault.iss").read_text(encoding="utf-8")
        match = re.search(r'#define MyAppVersion "([^"]+)"', iss)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), APP_VERSION)
        self.assertIn(f"PC_Backup_Vault_{APP_VERSION}_Setup", iss)

    def test_release_pipeline_runs_full_regression_and_hashes_setup(self):
        wf = (ROOT / ".github" / "workflows" / "release-windows.yml").read_text(encoding="utf-8")
        self.assertIn("Vollständige Regression", wf)
        self.assertIn("unittest discover -s project_finder/tests", wf)
        self.assertIn("unittest discover -s tests", wf)
        self.assertIn("Get-FileHash", wf)
        self.assertIn("Setup.exe.sha256", wf)
        self.assertIn("pyinstaller", wf)

    def test_deep_tuev_runs_on_linux_and_windows(self):
        wf = (ROOT / ".github" / "workflows" / "deep-tuev.yml").read_text(encoding="utf-8")
        self.assertIn("ubuntu-latest", wf)
        self.assertIn("windows-latest", wf)
        self.assertIn("Vollständige Root-Regression", wf)
        self.assertIn("Windows-Laufwerksinventar real prüfen", wf)
        self.assertIn("import app", wf)
        self.assertIn("pip check", wf)

    def test_windows_build_has_full_collection_regression(self):
        wf = (ROOT / ".github" / "workflows" / "build-windows.yml").read_text(encoding="utf-8")
        self.assertIn("Vollständige Gesamtregression", wf)
        self.assertIn("test_windows_drive_inventory_v1924", wf)
        self.assertIn("test_drive_inventory_integration_v1924", wf)
        self.assertIn("Windows-Laufwerksinventar real prüfen", wf)
        self.assertIn("App-Integrationskette importieren", wf)


if __name__ == "__main__":
    unittest.main()
