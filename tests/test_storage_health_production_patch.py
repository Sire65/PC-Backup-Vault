import os
import tempfile
import unittest

from storage_health_v193 import collect_storage_health


class Store:
    def __init__(self, data=None):
        self.data = data or {}


class StorageHealthProductionPatchTests(unittest.TestCase):
    def test_always_returns_three_expected_slots(self):
        rows = collect_storage_health(Store())
        self.assertEqual([row["id"] for row in rows], ["nas_backup", "hidrive_1", "hidrive_2"])
        self.assertEqual(rows[0]["status"], "not_configured")
        self.assertEqual(rows[1]["status"], "not_configured")
        self.assertEqual(rows[2]["status"], "not_configured")

    def test_reachable_nas_is_healthy_without_exposing_path(self):
        with tempfile.TemporaryDirectory() as target:
            rows = collect_storage_health(Store({
                "filesystem_targets": [{"kind": "NAS", "name": "NAS", "path": target}],
            }))
        self.assertEqual(rows[0]["status"], "healthy")
        self.assertNotIn(target, str(rows[0]))

    def test_configured_hidrive_is_unknown_until_transport_release(self):
        rows = collect_storage_health(Store({
            "cloud_accounts": [
                {"provider_code": "STRATO_HIDRIVE", "name": "HiDrive A", "enabled": True},
            ],
        }))
        self.assertEqual(rows[1]["status"], "unknown")
        self.assertEqual(rows[2]["status"], "not_configured")

    def test_sensitive_values_are_not_emitted(self):
        secret_path = r"C:\\private\\backup"
        rows = collect_storage_health(Store({
            "filesystem_targets": [{"kind": "NAS", "name": "NAS", "path": secret_path}],
            "cloud_accounts": [{
                "provider_code": "STRATO_HIDRIVE",
                "name": "HiDrive 1",
                "enabled": True,
                "username": "secret-user",
                "password": "secret-password",
                "endpoint": "secret-endpoint",
            }],
        }))
        text = str(rows)
        self.assertNotIn(secret_path, text)
        self.assertNotIn("secret-user", text)
        self.assertNotIn("secret-password", text)
        self.assertNotIn("secret-endpoint", text)


if __name__ == "__main__":
    unittest.main()
