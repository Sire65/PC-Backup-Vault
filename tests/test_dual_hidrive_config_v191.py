import unittest

from storage_health_v193 import collect_storage_health


class Store:
    def __init__(self, data):
        self.data = data


class DualHiDriveConfigTests(unittest.TestCase):
    def test_two_configured_hidrive_accounts_fill_both_slots(self):
        rows = collect_storage_health(Store({
            "cloud_accounts": [
                {"provider_code": "STRATO_HIDRIVE", "name": "HiDrive A", "enabled": True},
                {"provider_code": "STRATO_HIDRIVE", "name": "HiDrive B", "enabled": True},
            ]
        }))
        self.assertEqual([row["id"] for row in rows], ["nas_backup", "b2_backup", "kc_archive_db", "hidrive_1", "hidrive_2"])
        by_id = {row["id"]: row for row in rows}
        self.assertEqual(by_id["hidrive_1"]["status"], "unknown")
        self.assertEqual(by_id["hidrive_2"]["status"], "unknown")
        self.assertEqual(by_id["hidrive_1"]["name"], "HiDrive A")
        self.assertEqual(by_id["hidrive_2"]["name"], "HiDrive B")


if __name__ == "__main__":
    unittest.main()
