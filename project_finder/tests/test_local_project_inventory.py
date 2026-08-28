import unittest

from project_finder.local_project_inventory import compare_local_to_git, detect_project, group_local_projects


class LocalProjectInventoryTests(unittest.TestCase):
    def test_detects_dp2(self):
        self.assertEqual(detect_project(r"D:\KC\Dienstplan\release\v0.19.55\index.html"), "DP2")

    def test_groups_real_scan_rows_without_fake_projects(self):
        rows = [
            {"path": r"D:\KC\PC-Backup-Vault\v1.7.3\main.py", "name": "main.py", "category": "source", "modified": 10, "modified_iso": "2026-08-27", "version_hint": "1.7.3", "duplicate_of": ""},
            {"path": r"D:\KC\PC-Backup-Vault\old.zip", "name": "old.zip", "category": "archive", "modified": 5, "modified_iso": "2026-08-20", "version_hint": "", "duplicate_of": "x"},
        ]
        grouped = group_local_projects(rows)
        self.assertEqual(len(grouped), 1)
        self.assertEqual(grouped[0]["project"], "PC Backup Vault")
        self.assertEqual(grouped[0]["source_count"], 1)
        self.assertEqual(grouped[0]["duplicate_count"], 1)

    def test_known_matching_version_is_same(self):
        local = {"versions": ["1.7.3"]}
        git = {"version": "1.7.3"}
        self.assertEqual(compare_local_to_git(local, git), "SAME")

    def test_unknown_difference_does_not_guess_newer(self):
        local = {"versions": ["1.7.4"]}
        git = {"version": "1.7.3"}
        self.assertEqual(compare_local_to_git(local, git), "NOT_CHECKED")


if __name__ == "__main__":
    unittest.main()
