import unittest
from unittest import mock

import cloud_targets_v191 as cloud


class DummyStore:
    def __init__(self):
        self.data = {"filesystem_targets": []}
        self.saved = 0
    def save(self):
        self.saved += 1


class CloudTargetsV191Tests(unittest.TestCase):
    def setUp(self):
        self.store = DummyStore()

    def test_strato_provider_exposes_multiple_access_methods(self):
        methods = cloud.PROVIDERS["STRATO_HIDRIVE"]["methods"]
        self.assertIn("SMB", methods)
        self.assertIn("WEBDAV", methods)
        self.assertIn("SFTP", methods)

    def test_strato_smb_path_is_unique_per_username(self):
        self.assertEqual(
            cloud.strato_smb_path("MeinUser"),
            r"\\meinuser.smb3.hidrive.strato.com\root",
        )

    @mock.patch("cloud_targets_v191.set_cloud_secret")
    def test_password_is_not_written_to_config(self, secret_writer):
        account_id = cloud.save_cloud_account(
            self.store,
            {
                "name": "HiDrive 1",
                "provider_code": "STRATO_HIDRIVE",
                "methods": ["SMB", "WEBDAV"],
                "preferred_method": "SMB",
                "username": "koch",
            },
            password="TOP-SECRET",
        )
        row = cloud.cloud_account(self.store, account_id)
        self.assertNotIn("password", row)
        self.assertNotIn("TOP-SECRET", repr(self.store.data))
        secret_writer.assert_called_with(account_id, "password", "TOP-SECRET")

    @mock.patch("cloud_targets_v191.set_cloud_secret")
    def test_smb_account_becomes_filesystem_bridge(self, _secret_writer):
        account_id = cloud.save_cloud_account(
            self.store,
            {
                "name": "HiDrive Backup",
                "provider_code": "STRATO_HIDRIVE",
                "methods": ["SMB"],
                "preferred_method": "SMB",
                "username": "konto1",
            },
            password="x",
        )
        target = cloud.ensure_filesystem_bridge(self.store, account_id)
        self.assertEqual(target["id"], f"cloud-{account_id}")
        self.assertEqual(target["kind"], "CLOUD-SMB")
        self.assertEqual(target["cloud_account_id"], account_id)
        self.assertEqual(target["path"], r"\\konto1.smb3.hidrive.strato.com\root")
        self.assertEqual(self.store.data["active_filesystem_target_id"], target["id"])

    @mock.patch("cloud_targets_v191.set_cloud_secret")
    def test_oauth_only_account_is_not_misrepresented_as_ready_backup_transport(self, _secret_writer):
        account_id = cloud.save_cloud_account(
            self.store,
            {
                "name": "OneDrive",
                "provider_code": "MICROSOFT_ONEDRIVE",
                "methods": ["OAUTH"],
                "preferred_method": "OAUTH",
            },
            password="",
        )
        row = cloud.cloud_account(self.store, account_id)
        self.assertIsNone(cloud.filesystem_capable_method(row))
        with self.assertRaises(RuntimeError):
            cloud.ensure_filesystem_bridge(self.store, account_id)

    @mock.patch("cloud_targets_v191.set_cloud_secret")
    def test_local_sync_account_is_usable_without_cloud_password(self, _secret_writer):
        account_id = cloud.save_cloud_account(
            self.store,
            {
                "name": "Dropbox lokal",
                "provider_code": "DROPBOX",
                "methods": ["LOCAL_SYNC"],
                "preferred_method": "LOCAL_SYNC",
                "local_path": r"C:\Users\Test\Dropbox",
            },
            password="",
        )
        target = cloud.ensure_filesystem_bridge(self.store, account_id)
        self.assertEqual(target["kind"], "CLOUD-SYNC")
        self.assertEqual(target["path"], r"C:\Users\Test\Dropbox")


if __name__ == "__main__":
    unittest.main()
