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
        self.assertEqual([row["id"] for row in rows], ["nas_backup", "hidrive_1", "hidrive_2"])
        self.assertEqual(rows[1]["status"], "unknown")
        self.assertEqual(rows[2]["status"], "unknown")
        self.assertEqual(rows[1]["name"], "HiDrive A")
        self.assertEqual(rows[2]["name"], "HiDrive B")


if __name__ == "__main__":
    unittest.main()
