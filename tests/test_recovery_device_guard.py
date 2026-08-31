import unittest

from nas_recovery.device_resolver import canonical_disk_id, drive_letter_from_path, parse_disk_resolution
from nas_recovery.target_guard import devices_are_distinct, image_target_disk_is_safe, recovery_target_is_safe


class RecoveryDeviceGuardTests(unittest.TestCase):
    def test_distinct_devices_require_all_identities(self):
        self.assertFalse(devices_are_distinct("disk-1", "disk-2", ""))
        self.assertFalse(devices_are_distinct("disk-1", "disk-2", "disk-2"))
        self.assertTrue(devices_are_distinct("disk-1", "disk-2", "disk-3"))
        self.assertTrue(recovery_target_is_safe("SRC", "IMG", "OUT"))

    def test_image_target_must_resolve_to_different_disk(self):
        self.assertFalse(image_target_disk_is_safe(3, None))
        self.assertFalse(image_target_disk_is_safe(3, 3))
        self.assertTrue(image_target_disk_is_safe(3, 8))

    def test_drive_letter_parsing(self):
        self.assertEqual(drive_letter_from_path(r"D:\images\disk.img"), "D")
        self.assertEqual(drive_letter_from_path("e:/recovered"), "E")
        self.assertEqual(drive_letter_from_path(r"\\server\share\file.img"), "")

    def test_read_only_resolution_uses_same_disk_number_namespace(self):
        result = parse_disk_resolution(r"D:\image.img", '{"DiskNumber":8,"UniqueId":"ABC-123"}')
        self.assertTrue(result.known)
        self.assertEqual(result.disk_number, 8)
        self.assertEqual(result.device_id, "disk-number:8")
        self.assertEqual(canonical_disk_id(8), result.device_id)

    def test_resolution_parser_fails_closed(self):
        result = parse_disk_resolution(r"D:\image.img", "not-json")
        self.assertFalse(result.known)
        self.assertEqual(result.device_id, "")


if __name__ == "__main__":
    unittest.main()
