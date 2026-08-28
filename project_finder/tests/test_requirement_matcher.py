import unittest

from project_finder.requirement_matcher import annotate_findings, match_requirement


class RequirementMatcherTests(unittest.TestCase):
    def test_no_evidence_is_not_checked(self):
        self.assertEqual(match_requirement("Pause Button blinkt", [])["state"], "NOT_CHECKED")

    def test_multiple_distinct_terms_can_match(self):
        result = match_requirement("Pause Button soll blinken", ["pause button blinkt bei angehaltener sicherung"])
        self.assertEqual(result["state"], "FOUND")
        self.assertGreaterEqual(len(result["matched_terms"]), 2)

    def test_single_generic_overlap_is_not_enough(self):
        result = match_requirement("Dashboard Geschwindigkeit Rundinstrument", ["dashboard status wird geladen"])
        self.assertEqual(result["state"], "MISSING")

    def test_annotation_is_project_scoped_across_aliases(self):
        rows = annotate_findings(
            [{"project": "Dienstplan", "text": "Fehleranalyse Button reparieren"}],
            {"PC Backup Vault": ["fehleranalyse button reparieren"], "Sire65/Dienstplan": ["fehleranalyse button reparieren"]},
        )
        self.assertEqual(rows[0]["project"], "DP2 / Dienstplan")
        self.assertEqual(rows[0]["git_requirement_match"], "FOUND")
        self.assertEqual(rows[0]["git_requirement_match_evidence_index"], 0)


if __name__ == "__main__":
    unittest.main()
