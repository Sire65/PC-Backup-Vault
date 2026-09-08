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
            def _build(self): return "old"
            def _media_rows(self): return []
            def _media_selected(self): return None
            def start_backup(self): return "engine"
            def restore(self): return "restore"

        start = DummyWorkbench.start_backup
        restore = DummyWorkbench.restore
        apply_backup_workbench_ui_v196(DummyWorkbench)
        first_build = DummyWorkbench._build
        apply_backup_workbench_ui_v196(DummyWorkbench)
        self.assertIs(DummyWorkbench._build, first_build)
        self.assertIs(DummyWorkbench.start_backup, start)
        self.assertIs(DummyWorkbench.restore, restore)
        self.assertTrue(DummyWorkbench._ui_v196)
        self.assertTrue(callable(DummyWorkbench._return_to_main_v197))

    def test_return_to_main_closes_workbench_and_restores_main_focus(self):
        class App:
            def __init__(self): self.calls = []
            def deiconify(self): self.calls.append("deiconify")
            def lift(self): self.calls.append("lift")
            def focus_force(self): self.calls.append("focus")

        class DummyWorkbench:
            def _build(self): pass
            def _media_rows(self): return []
            def _media_selected(self): pass
            def _close(self): self.closed = True

        apply_backup_workbench_ui_v196(DummyWorkbench)
        obj = DummyWorkbench()
        obj.app = App()
        obj.closed = False
        result = obj._return_to_main_v197()
        self.assertTrue(obj.closed)
        self.assertEqual(obj.app.calls, ["deiconify", "lift", "focus"])
        self.assertEqual(result, "break")


if __name__ == "__main__":
    unittest.main()
