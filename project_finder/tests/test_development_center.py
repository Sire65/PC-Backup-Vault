import unittest

from project_finder.development_center import DevelopmentItem, decide_status


class DevelopmentCenterTests(unittest.TestCase):
    def test_green_requires_known_non_newer_local_state(self):
        item = DevelopmentItem("DP2", "x", git_evidence="FOUND", test_evidence="PASS", local_git_relation="SAME")
        self.assertEqual(decide_status(item).status, "GREEN")

    def test_local_newer_blocks_green(self):
        item = DevelopmentItem("DP2", "x", git_evidence="FOUND", test_evidence="PASS", local_git_relation="LOCAL_NEWER")
        self.assertEqual(decide_status(item).status, "RED")

    def test_diverged_blocks_green(self):
        item = DevelopmentItem("DP2", "x", git_evidence="FOUND", test_evidence="PASS", local_git_relation="DIVERGED")
        self.assertEqual(decide_status(item).status, "RED")

    def test_failed_test_is_red(self):
        item = DevelopmentItem("DP2", "x", git_evidence="FOUND", test_evidence="FAIL", local_git_relation="SAME")
        self.assertEqual(decide_status(item).status, "RED")

    def test_missing_idea_is_not_called_lost_development(self):
        item = DevelopmentItem("DP2", "new idea", chat_claim="IDEA", git_evidence="MISSING")
        result = decide_status(item)
        self.assertEqual(result.status, "YELLOW")
        self.assertIn("kein Beleg", result.reason)

    def test_local_only_evidence_is_red(self):
        item = DevelopmentItem("DP2", "x", git_evidence="MISSING", local_evidence="FOUND")
        self.assertEqual(decide_status(item).status, "RED")


if __name__ == "__main__":
    unittest.main()
