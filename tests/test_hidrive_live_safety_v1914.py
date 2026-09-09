import unittest

import hidrive_live_explorer_v1914 as live
from hidrive_live_safety_v1914 import apply_hidrive_live_safety_v1914


class HiDriveLiveSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        apply_hidrive_live_safety_v1914(live)

    def test_nested_backup_vault_is_protected(self):
        home = "/users/hausmeister1"
        self.assertTrue(live._is_protected(
            "/users/hausmeister1/PC_Backup_Vault/.pc-backup-vault/jobs/abc.json",
            home,
        ))

    def test_normal_folder_is_not_protected(self):
        self.assertFalse(live._is_protected(
            "/users/hausmeister1/Dokumente/Rechnung.pdf",
            "/users/hausmeister1",
        ))

    def test_path_outside_home_is_not_considered_mutable_protected_area(self):
        self.assertFalse(live._is_protected(
            "/users/anderer/.pc-backup-vault/jobs/abc.json",
            "/users/hausmeister1",
        ))

    def test_disabled_accounts_are_filtered(self):
        class Store:
            def __init__(self):
                self.data = {"cloud_accounts": [
                    {"id": "on", "provider_code": "STRATO_HIDRIVE", "methods": ["SFTP"], "preferred_method": "SFTP", "enabled": True},
                    {"id": "off", "provider_code": "STRATO_HIDRIVE", "methods": ["SFTP"], "preferred_method": "SFTP", "enabled": False},
                ]}
            def save(self):
                pass
        self.assertEqual([x["id"] for x in live._hidrive_accounts(Store())], ["on"])


if __name__ == "__main__":
    unittest.main()
