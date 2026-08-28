import unittest

from project_finder.change_dashboard_model import summarize_changes


class ChangeDashboardModelTests(unittest.TestCase):
    def test_counts_projects_and_attention(self):
        rows = [
            {"project": "DP2 / Dienstplan", "kind": "OPEN_OR_ERROR"},
            {"project": "DP2 / Dienstplan", "kind": "IDEA_OR_REQUIREMENT"},
            {"project": "PC Backup Vault", "kind": "IMPLEMENTATION_CLAIM"},
        ]
        result = summarize_changes(rows)
        self.assertEqual(result["counts"]["new"], 3)
        self.assertEqual(result["counts"]["projects_affected"], 2)
        self.assertEqual(result["counts"]["open_or_error"], 1)
        self.assertEqual(result["counts"]["ideas"], 1)
        self.assertEqual(len(result["attention"]), 1)

    def test_empty_is_zero_not_fake_data(self):
        result = summarize_changes([])
        self.assertEqual(result["counts"]["new"], 0)
        self.assertEqual(result["projects"], {})


if __name__ == "__main__":
    unittest.main()
