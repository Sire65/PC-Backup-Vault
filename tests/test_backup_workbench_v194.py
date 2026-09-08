import tempfile
import unittest
from pathlib import Path

from backup_workbench_v194 import (
    active_filesystem_targets, builtin_enabled, ensure_media_config,
    set_builtin_enabled, set_target_enabled, target_enabled,
)


class DummyStore:
    def __init__(self, root):
        self.path = Path(root) / "config.json"
        self.data = {"filesystem_targets": [], "plans": [], "cloud_accounts": []}
        self.saved = 0
    def save(self):
        self.saved += 1


class BackupWorkbenchV194Tests(unittest.TestCase):
    def test_defaults_are_additive_and_do_not_remove_existing_targets(self):
        with tempfile.TemporaryDirectory() as td:
            s = DummyStore(td)
            s.data["filesystem_targets"] = [{"id":"nas1","name":"NAS","path":"X:/backup","kind":"NAS"}]
            ensure_media_config(s)
            self.assertEqual(len(s.data["filesystem_targets"]), 1)
            self.assertTrue(s.data["filesystem_targets"][0]["enabled"])
            self.assertTrue(builtin_enabled(s, "B2"))
            self.assertTrue(builtin_enabled(s, "NEON"))

    def test_disabling_target_keeps_definition_but_excludes_it_and_clears_active(self):
        with tempfile.TemporaryDirectory() as td:
            s = DummyStore(td)
            s.data["filesystem_targets"] = [{"id":"usb1","name":"USB","path":"E:/PBV","kind":"ORDNER","enabled":True}]
            s.data["active_filesystem_target_id"] = "usb1"
            affected = set_target_enabled(s, "usb1", False)
            self.assertEqual(affected, 0)
            self.assertEqual(len(s.data["filesystem_targets"]), 1)
            self.assertFalse(s.data["filesystem_targets"][0]["enabled"])
            self.assertIsNone(s.data["active_filesystem_target_id"])
            self.assertEqual(active_filesystem_targets(s), [])

    def test_plan_reference_is_reported_when_medium_is_disabled(self):
        with tempfile.TemporaryDirectory() as td:
            s = DummyStore(td)
            s.data["filesystem_targets"] = [{"id":"nas1","name":"NAS","path":"//nas/backup","kind":"NAS","enabled":True}]
            s.data["plans"] = [{"id":"p1","enabled":True,"filesystem_target_id":"nas1"},{"id":"p2","enabled":False,"filesystem_target_id":"nas1"}]
            self.assertEqual(set_target_enabled(s, "nas1", False), 1)
            self.assertEqual(len(s.data["plans"]), 2)

    def test_builtin_media_can_be_excluded_and_reenabled_without_losing_config(self):
        with tempfile.TemporaryDirectory() as td:
            s = DummyStore(td)
            s.data["b2"] = {"enabled":True,"bucket":"keep-this"}
            set_builtin_enabled(s, "B2", False)
            self.assertFalse(builtin_enabled(s, "B2"))
            self.assertEqual(s.data["b2"]["bucket"], "keep-this")
            set_builtin_enabled(s, "B2", True)
            self.assertTrue(builtin_enabled(s, "B2"))

    def test_linked_cloud_target_follows_cloud_account_enabled_state(self):
        with tempfile.TemporaryDirectory() as td:
            s = DummyStore(td)
            s.data["cloud_accounts"] = [{"id":"c1","name":"HiDrive","enabled":False}]
            t = {"id":"cloud-c1","name":"Cloud","path":"/users/test","kind":"CLOUD-SFTP","cloud_account_id":"c1","enabled":True}
            s.data["filesystem_targets"] = [t]
            self.assertFalse(target_enabled(s, t))
            s.data["cloud_accounts"][0]["enabled"] = True
            self.assertTrue(target_enabled(s, t))


if __name__ == "__main__":
    unittest.main()
