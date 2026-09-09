import unittest

from backup_completion_ui_v1923 import is_hidrive_success, target_description


class DummyStore:
    def __init__(self):
        self.data = {
            "active_filesystem_target_id": "cloud-sire25",
            "filesystem_targets": [
                {
                    "id": "cloud-sire25",
                    "name": "Cloud · Strato_sire25",
                    "path": "/users/sire25/PC_Backup_Vault",
                    "cloud_account_id": "sire25",
                    "cloud_method": "SFTP",
                }
            ],
            "cloud_accounts": [
                {"id": "sire25", "name": "Strato_sire25", "provider": "STRATO_HIDRIVE"}
            ],
        }


class DummyApp:
    def __init__(self, code="FILESYSTEM"):
        self.code = code
        self.store = DummyStore()

    def _selected_payload_code(self):
        return self.code


class BackupCompletionUiTests(unittest.TestCase):
    def test_hidrive_target_is_exact(self):
        self.assertEqual(
            target_description(DummyApp()),
            "STRATO HiDrive · Strato_sire25 · /users/sire25/PC_Backup_Vault",
        )

    def test_builtin_targets_have_clear_names(self):
        self.assertEqual(target_description(DummyApp("B2")), "Backblaze B2 + Neon-Core")
        self.assertEqual(target_description(DummyApp("NEON")), "Neon – nur Kleinmengen")

    def test_only_hidrive_success_requests_auto_report(self):
        self.assertTrue(is_hidrive_success(
            "backup_success", "STRATO HiDrive Backup erfolgreich",
            {"job_id": "job-1", "target": "Cloud · Strato_sire25"},
        ))
        self.assertFalse(is_hidrive_success(
            "backup_success", "Backup erfolgreich",
            {"job_id": "job-2", "target": "Backblaze B2 + Neon-Core"},
        ))
        self.assertFalse(is_hidrive_success(
            "backup_failed", "STRATO HiDrive Backup fehlgeschlagen",
            {"job_id": "job-3", "target": "Cloud · Strato_sire25"},
        ))
        self.assertFalse(is_hidrive_success(
            "backup_success", "STRATO HiDrive Backup erfolgreich", {},
        ))


if __name__ == "__main__":
    unittest.main()
