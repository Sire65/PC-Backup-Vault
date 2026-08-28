import unittest
from project_finder.requirement_matcher import annotate_findings, match_requirement

class RequirementMatcherTests(unittest.TestCase):
    def test_no_evidence_is_not_checked(self): self.assertEqual(match_requirement("Pause Button blinkt", [])["state"], "NOT_CHECKED")
    def test_multiple_distinct_terms_can_match(self):
        result=match_requirement("Pause Button soll blinken", ["pause button blinkt bei angehaltener sicherung"]); self.assertEqual(result["state"],"FOUND"); self.assertGreaterEqual(len(result["matched_terms"]),2)
    def test_single_generic_overlap_is_not_enough(self): self.assertEqual(match_requirement("Dashboard Geschwindigkeit Rundinstrument", ["dashboard status wird geladen"])["state"],"MISSING")
    def test_filename_only_can_never_be_found(self):
        result=match_requirement("Pause Button blinkt", [{"kind":"filename","text":"pause_button_blinkt.py","ref":"tree"}]); self.assertEqual(result["state"],"WEAK_ONLY"); self.assertEqual(result["evidence_kind"],"filename")
    def test_path_only_can_never_be_found(self):
        result=match_requirement("Dashboard Geschwindigkeit Rundinstrument", [{"kind":"path","text":"ui/dashboard_geschwindigkeit_rundinstrument.py"}]); self.assertNotEqual(result["state"],"FOUND")
    def test_strong_content_can_be_found(self):
        result=match_requirement("Pause Button blinkt", [{"kind":"content","text":"pause button blinkt bei angehaltener sicherung","ref":"ui.py:120"}]); self.assertEqual(result["state"],"FOUND"); self.assertEqual(result["evidence_ref"],"ui.py:120")
    def test_annotation_is_project_scoped_across_aliases(self):
        rows=annotate_findings([{"project":"Dienstplan","text":"Fehleranalyse Button reparieren"}],{"PC Backup Vault":["fehleranalyse button reparieren"],"Sire65/Dienstplan":["fehleranalyse button reparieren"]})
        self.assertEqual(rows[0]["project"],"DP2 / Dienstplan"); self.assertEqual(rows[0]["git_requirement_match"],"FOUND"); self.assertEqual(rows[0]["git_requirement_match_evidence_index"],0)

if __name__ == "__main__": unittest.main()
