import os
import unittest
from unittest.mock import patch

import windows_drive_inventory_v1924 as inv
import drive_inventory_tuev_v1924 as tuev


class WindowsDriveInventoryV1924Tests(unittest.TestCase):
    def test_merge_uses_union_and_keeps_unready_native_drive(self):
        rows = inv.merge_drive_roots(
            ["C:\\", "E:\\"],
            ["C:\\", "D:\\", "F:\\"],
            ["G:\\"],
        )
        self.assertEqual(rows, ["C:\\", "D:\\", "E:\\", "F:\\", "G:\\"])

    def test_normalize_drive_root(self):
        self.assertEqual(inv.normalize_drive_root("c:"), "C:\\")
        self.assertEqual(inv.normalize_drive_root("e:\\Daten"), "E:\\")
        self.assertEqual(inv.normalize_drive_root(""), "")

    def test_discovery_combines_python_native_and_fallback(self):
        with patch.object(inv.os, "name", "nt"), \
             patch.object(inv, "_python_drives", return_value=["C:\\", "D:\\"]), \
             patch.object(inv, "_native_drives", return_value=["C:\\", "E:\\", "F:\\"]), \
             patch.object(inv, "_exists_fallback_drives", return_value=["G:\\"]):
            self.assertEqual(inv.discover_drive_roots(), ["C:\\", "D:\\", "E:\\", "F:\\", "G:\\"])

    def test_display_contains_label_type_and_unreachable_state(self):
        text = inv.drive_display("E:\\", label="Backup SSD", type_code=3, ready=True)
        self.assertEqual(text, "E:  Backup SSD · Lokaler Datenträger")
        text = inv.drive_display("Z:\\", label="Archiv", type_code=4, ready=False)
        self.assertIn("Z:  Archiv", text)
        self.assertIn("Netzlaufwerk", text)
        self.assertIn("nicht erreichbar", text)

    def test_inventory_check_reports_count_and_system_drive(self):
        fake = [
            {"root": "C:\\", "display": "C: Windows · Lokaler Datenträger"},
            {"root": "D:\\", "display": "D: Daten · Lokaler Datenträger"},
            {"root": "E:\\", "display": "E: Backup · Lokaler Datenträger"},
        ]
        with patch.object(tuev.os, "name", "nt"), \
             patch.dict(os.environ, {"SystemDrive": "C:"}, clear=False), \
             patch.object(tuev, "drive_inventory", return_value=fake):
            code, title, status, detail = tuev.drive_inventory_check()
        self.assertEqual(code, "DRV-001")
        self.assertEqual(status, "PASS")
        self.assertIn("3 Laufwerk(e) erkannt", detail)
        self.assertIn("E: Backup", detail)

    def test_inventory_check_warns_if_system_drive_missing(self):
        fake = [{"root": "D:\\", "display": "D: Daten"}]
        with patch.object(tuev.os, "name", "nt"), \
             patch.dict(os.environ, {"SystemDrive": "C:"}, clear=False), \
             patch.object(tuev, "drive_inventory", return_value=fake):
            _code, _title, status, detail = tuev.drive_inventory_check()
        self.assertEqual(status, "WARN")
        self.assertIn("Systemlaufwerk C:\\ fehlt", detail)


if __name__ == "__main__":
    unittest.main()
