import tempfile
import unittest
from pathlib import Path

from storage_health_v193 import collect_storage_health


class Store:
    def __init__(self, data):
        self.data = data


class StorageHealthV193Tests(unittest.TestCase):
    def test_nas_and_two_hidrive_slots_are_reported_without_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store({
                "filesystem_targets": [{"id": "n1", "name": "Mein NAS", "kind": "NAS", "path": tmp}],
                "cloud_accounts": [
                    {"id": "h1", "name": "HiDrive Privat", "provider_code": "STRATO_HIDRIVE", "enabled": True},
                    {"id": "h2", "name": "HiDrive Technik", "provider_code": "STRATO_HIDRIVE", "enabled": True},
                ],
            })

            def probe(_store, account_id):
                return (account_id == "h1", 12, "C:\\secret\\path")

            rows = collect_storage_health(store, probe)
            self.assertEqual([r["id"] for r in rows], ["nas_backup", "hidrive_1", "hidrive_2"])
            self.assertEqual(rows[0]["status"], "healthy")
            self.assertEqual(rows[1]["status"], "healthy")
            self.assertEqual(rows[2]["status"], "critical")
            self.assertNotIn(tmp, repr(rows))
            self.assertNotIn("C:\\secret", repr(rows))

    def test_unconfigured_targets_are_not_reported_as_green(self):
        rows = collect_storage_health(Store({"filesystem_targets": [], "cloud_accounts": []}), lambda *_: (True, 1, "ok"))
        self.assertEqual(rows[0]["status"], "not_configured")
        self.assertEqual(rows[1]["status"], "not_configured")
        self.assertEqual(rows[2]["status"], "not_configured")


if __name__ == "__main__":
    unittest.main()
