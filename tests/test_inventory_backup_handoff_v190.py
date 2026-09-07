import unittest

from project_finder.backup_handoff_v190 import inventory_backup_sources


class _Finder:
    def __init__(self, selected=None, roots=None):
        self._selected = selected or []
        self.roots = roots or []

    def selected_paths(self):
        return list(self._selected)


class InventoryBackupHandoffTests(unittest.TestCase):
    def test_selected_inventory_rows_are_handed_off(self):
        finder = _Finder(selected=[r"C:\KC\dp2\app.py", r"C:\KC\dp2\README.md"], roots=[r"C:\KC"])
        sources, mode = inventory_backup_sources(finder)
        self.assertEqual(mode, "SELECTION")
        self.assertEqual(sources, [r"C:\KC\dp2\app.py", r"C:\KC\dp2\README.md"])

    def test_scan_roots_are_fallback_when_nothing_selected(self):
        finder = _Finder(selected=[], roots=[r"D:\Altprojekte", r"E:\KC"])
        sources, mode = inventory_backup_sources(finder)
        self.assertEqual(mode, "ROOTS")
        self.assertEqual(sources, [r"D:\Altprojekte", r"E:\KC"])

    def test_duplicate_paths_are_removed_case_insensitively(self):
        finder = _Finder(selected=[r"C:\KC\DP2", r"c:\kc\dp2"])
        sources, mode = inventory_backup_sources(finder)
        self.assertEqual(mode, "SELECTION")
        self.assertEqual(len(sources), 1)


if __name__ == "__main__":
    unittest.main()
