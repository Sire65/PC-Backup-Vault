import tempfile
import unittest
from pathlib import Path

from backup_source_selection_safety_v1922 import merge_sources_safely, source_overlaps, source_label


class SourceSelectionSafetyTests(unittest.TestCase):
    def test_child_replaces_existing_parent(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "Peter"
            root.mkdir()
            child = root / "eine_datei.xlsx"
            child.write_text("x", encoding="utf-8")
            merged, removed, blocked = merge_sources_safely([str(root)], [str(child)])
            self.assertEqual(merged, [str(child)])
            self.assertEqual(removed, [str(root)])
            self.assertEqual(blocked, [])

    def test_parent_is_blocked_when_precise_child_already_selected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "Peter"
            root.mkdir()
            child = root / "eine_datei.xlsx"
            child.write_text("x", encoding="utf-8")
            merged, removed, blocked = merge_sources_safely([str(child)], [str(root)])
            self.assertEqual(merged, [str(child)])
            self.assertEqual(removed, [])
            self.assertEqual(blocked, [str(root)])

    def test_same_multi_selection_keeps_narrower_child(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "Peter"
            root.mkdir()
            child = root / "eine_datei.xlsx"
            child.write_text("x", encoding="utf-8")
            merged, removed, blocked = merge_sources_safely([], [str(root), str(child)])
            self.assertEqual(merged, [str(child)])
            self.assertEqual(removed, [])
            self.assertEqual(blocked, [])

    def test_overlap_detector_finds_parent_and_child(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "Peter"
            root.mkdir()
            child = root / "eine_datei.xlsx"
            child.write_text("x", encoding="utf-8")
            self.assertEqual(source_overlaps([str(root), str(child)]), [(str(root), str(child))])

    def test_source_labels_show_type(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "Peter"
            root.mkdir()
            child = root / "eine_datei.xlsx"
            child.write_text("x", encoding="utf-8")
            self.assertTrue(source_label(str(root)).startswith("[ORDNER]"))
            self.assertTrue(source_label(str(child)).startswith("[DATEI]"))


if __name__ == "__main__":
    unittest.main()
