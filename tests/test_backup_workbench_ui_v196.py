import unittest

from backup_workbench_ui_v196 import _safe_cloud_path, apply_backup_workbench_ui_v196


class BackupWorkbenchUiV196Tests(unittest.TestCase):
    def test_cloud_internal_root_is_hidden(self):
        row = {"account_id": "private-id", "path": "/users/sire25/PC_Backup_Vault"}
        self.assertEqual(_safe_cloud_path(row), "PC_Backup_Vault")
        self.assertNotIn("/users/", _safe_cloud_path(row))

    def test_local_target_path_is_preserved(self):
        row = {"target_id": "local", "path": "L:/Test Backup"}
        self.assertEqual(_safe_cloud_path(row), "L:/Test Backup")

    def test_ui_patch_is_idempotent_and_engine_methods_untouched(self):
        class DummyWorkbench:
            def _build(self):
                return "old"
            def _media_rows(self):
                return []
            def _media_selected(self):
                return None
            def start_backup(self):
                return "engine"
            def restore(self):
                return "restore"

        start = DummyWorkbench.start_backup
        restore = DummyWorkbench.restore
        apply_backup_workbench_ui_v196(DummyWorkbench)
        first_build = DummyWorkbench._build
        apply_backup_workbench_ui_v196(DummyWorkbench)
        self.assertIs(DummyWorkbench._build, first_build)
        self.assertIs(DummyWorkbench.start_backup, start)
        self.assertIs(DummyWorkbench.restore, restore)
        self.assertTrue(DummyWorkbench._ui_v196)


if __name__ == "__main__":
    unittest.main()
