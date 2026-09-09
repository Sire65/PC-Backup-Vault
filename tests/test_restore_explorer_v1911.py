import unittest

from archive_restore_selective_v1911 import filter_manifest
from restore_explorer_v1911 import manifest_index_from_file_key


class RestoreExplorerV1911Tests(unittest.TestCase):
    def test_manifest_index_parser(self):
        self.assertEqual(manifest_index_from_file_key("MANIFEST:job-1:0:abc"), 0)
        self.assertEqual(manifest_index_from_file_key("MANIFEST:job-1:42:def"), 42)
        self.assertIsNone(manifest_index_from_file_key("DB:123"))
        self.assertIsNone(manifest_index_from_file_key("MANIFEST:broken"))

    def test_filter_manifest_only_selected_files(self):
        manifest = {
            "job_id": "j",
            "files": [
                {"name": "a", "original_size": 10},
                {"name": "b", "original_size": 20},
                {"name": "c", "original_size": 30},
            ],
        }
        result = filter_manifest(manifest, {0, 2})
        self.assertEqual([x["name"] for x in result["files"]], ["a", "c"])
        self.assertEqual(result["file_count"], 2)
        self.assertEqual(result["original_bytes"], 40)
        self.assertEqual(len(manifest["files"]), 3)

    def test_filter_manifest_rejects_empty_selection(self):
        with self.assertRaises(ValueError):
            filter_manifest({"files": [{"name": "a"}]}, set())

    def test_filter_manifest_rejects_missing_indices(self):
        with self.assertRaises(ValueError):
            filter_manifest({"files": [{"name": "a"}]}, {99})


if __name__ == "__main__":
    unittest.main()
