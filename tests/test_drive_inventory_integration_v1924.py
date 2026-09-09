import types
import unittest
from unittest.mock import patch

import drive_inventory_integration_v1924 as integration


class FakeTree:
    def __init__(self):
        self.rows = []

    def get_children(self):
        return [str(i) for i in range(len(self.rows))]

    def delete(self, *items):
        self.rows.clear()

    def insert(self, parent, where, **kwargs):
        self.rows.append({"parent": parent, "where": where, **kwargs})
        return str(len(self.rows) - 1)


class FakeWorkbench:
    _drive_inventory_v1924 = False

    def __init__(self):
        self.src_tree = FakeTree()


class FakeStorageCenter:
    _drive_inventory_v1924 = False

    def __init__(self):
        self.calls = []

    def _insert(self, parent, item, text, values, expandable=False):
        self.calls.append((parent, item, text, tuple(values), expandable))
        return "iid"


class DriveInventoryIntegrationV1924Tests(unittest.TestCase):
    def setUp(self):
        FakeWorkbench._drive_inventory_v1924 = False
        FakeStorageCenter._drive_inventory_v1924 = False
        FakeStorageCenter._insert = self._base_insert

    @staticmethod
    def _base_insert(self, parent, item, text, values, expandable=False):
        self.calls.append((parent, item, text, tuple(values), expandable))
        return "iid"

    def test_workbench_shows_every_inventory_row_but_keeps_raw_path(self):
        fake_module = types.SimpleNamespace(_windows_drives=lambda: ["OLD"])
        rows = [
            {"root": "C:\\", "display": "C:  Windows · Lokaler Datenträger"},
            {"root": "D:\\", "display": "D:  Daten · Lokaler Datenträger"},
            {"root": "Z:\\", "display": "Z:  NAS · Netzlaufwerk · nicht erreichbar"},
        ]
        with patch.object(integration, "drive_inventory", return_value=rows):
            integration.apply_drive_inventory_v1924(FakeWorkbench, fake_module, FakeStorageCenter)
            wb = FakeWorkbench()
            wb._load_source_browser()

        top = [r for r in wb.src_tree.rows if r["parent"] == ""]
        self.assertEqual(len(top), 3)
        self.assertEqual(top[1]["values"], ("D:\\",))
        self.assertIn("D:  Daten", top[1]["text"])
        self.assertIs(fake_module._windows_drives, integration.discover_drive_roots)

    def test_storage_center_decorates_drive_name_without_corrupting_path(self):
        fake_module = types.SimpleNamespace(_windows_drives=lambda: [])
        integration.apply_drive_inventory_v1924(FakeWorkbench, fake_module, FakeStorageCenter)
        center = FakeStorageCenter()
        item = {"backend": "FILESYSTEM", "drive_root": True, "path": "E:\\", "name": "E:\\"}
        with patch.object(integration, "drive_display", return_value="E:  Backup SSD · Lokaler Datenträger"), \
             patch.object(integration, "drive_type_label", return_value="Lokaler Datenträger"):
            center._insert("root", item, "💽 E:\\", ("Laufwerk", "–", "–", "E:\\"), expandable=True)

        _parent, saved_item, text, values, expandable = center.calls[-1]
        self.assertEqual(saved_item["path"], "E:\\")
        self.assertEqual(values[3], "E:\\")
        self.assertEqual(values[0], "Lokaler Datenträger")
        self.assertIn("Backup SSD", text)
        self.assertTrue(expandable)


if __name__ == "__main__":
    unittest.main()
