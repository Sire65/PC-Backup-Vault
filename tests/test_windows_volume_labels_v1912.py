import unittest

from windows_volume_labels_v1912 import format_drive_display, format_location_display, is_drive_root, normalize_drive_root


class WindowsVolumeLabelsV1912Tests(unittest.TestCase):
    def test_drive_root_detection(self):
        self.assertTrue(is_drive_root("C:\\"))
        self.assertTrue(is_drive_root("D:"))
        self.assertFalse(is_drive_root("C:\\Users"))
        self.assertFalse(is_drive_root("\\\\NAS\\Backup"))

    def test_normalize_drive_root(self):
        self.assertEqual(normalize_drive_root("C:\\Users\\Hans"), "C:\\")
        self.assertEqual(normalize_drive_root("E:"), "E:\\")

    def test_format_drive_with_label(self):
        self.assertEqual(format_drive_display("C:\\", "Windows"), "C:  Windows")
        self.assertEqual(format_drive_display("E:\\", "Backup SSD"), "E:  Backup SSD")

    def test_format_drive_without_label(self):
        self.assertEqual(format_drive_display("D:\\", ""), "D:")

    def test_location_display_keeps_folder_name(self):
        self.assertEqual(format_location_display("C:\\Daten\\Projekte"), "Projekte")


if __name__ == "__main__":
    unittest.main()
