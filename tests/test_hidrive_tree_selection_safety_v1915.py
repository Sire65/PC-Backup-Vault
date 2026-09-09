import unittest

from hidrive_tree_selection_safety_v1915 import _prune_nested_rows


class HiDriveTreeSelectionSafetyTests(unittest.TestCase):
    def test_child_is_removed_when_parent_folder_is_selected(self):
        rows = [
            {"path": "/users/demo/Fotos/2026/bild.jpg", "is_dir": False},
            {"path": "/users/demo/Fotos", "is_dir": True},
        ]
        result = _prune_nested_rows(rows)
        self.assertEqual([row["path"] for row in result], ["/users/demo/Fotos"])

    def test_sibling_selections_are_kept(self):
        rows = [
            {"path": "/users/demo/Fotos", "is_dir": True},
            {"path": "/users/demo/Dokumente", "is_dir": True},
            {"path": "/users/demo/a.txt", "is_dir": False},
        ]
        result = _prune_nested_rows(rows)
        self.assertEqual(len(result), 3)

    def test_file_does_not_hide_descendant_by_name_prefix(self):
        rows = [
            {"path": "/users/demo/a", "is_dir": False},
            {"path": "/users/demo/a/b.txt", "is_dir": False},
        ]
        result = _prune_nested_rows(rows)
        self.assertEqual(len(result), 2)


if __name__ == "__main__":
    unittest.main()
