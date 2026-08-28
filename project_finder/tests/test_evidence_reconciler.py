import unittest

from project_finder.evidence_reconciler import reconcile_evidence
from project_finder.git_inventory import RepoSnapshot


class EvidenceReconcilerTests(unittest.TestCase):
    def test_repo_presence_alone_does_not_make_requirement_green(self):
        findings = [{"project": "DP2 / Dienstplan", "kind": "IMPLEMENTATION_CLAIM", "text": "Fehleranalyse ist fertig"}]
        repos = [RepoSnapshot(project="DP2 / Dienstplan", repository="Sire65/Dienstplan", head_sha="abc", latest_test="PASS", local_state="SAME")]
        result = reconcile_evidence(findings, repos)
        self.assertEqual(result["items"][0]["status"], "YELLOW")

    def test_explicit_requirement_match_plus_pass_is_green(self):
        findings = [{"project": "DP2 / Dienstplan", "kind": "IMPLEMENTATION_CLAIM", "text": "Fehleranalyse ist fertig", "git_requirement_match": "FOUND"}]
        repos = [RepoSnapshot(project="DP2 / Dienstplan", repository="Sire65/Dienstplan", head_sha="abc", latest_test="PASS", local_state="SAME")]
        result = reconcile_evidence(findings, repos)
        self.assertEqual(result["items"][0]["status"], "GREEN")

    def test_local_newer_blocks_green_even_with_requirement_match(self):
        findings = [{"project": "DP2 / Dienstplan", "kind": "IMPLEMENTATION_CLAIM", "text": "Fehleranalyse ist fertig", "git_requirement_match": "FOUND"}]
        repos = [RepoSnapshot(project="DP2 / Dienstplan", repository="Sire65/Dienstplan", head_sha="abc", latest_test="PASS", local_state="LOCAL_NEWER")]
        result = reconcile_evidence(findings, repos)
        self.assertEqual(result["items"][0]["status"], "RED")

    def test_local_only_project_is_red_possible_lost_development(self):
        findings = [{"project": "KC Manager", "kind": "IMPLEMENTATION_CLAIM", "text": "Leitstand eingebaut"}]
        local = [{"project": "KC Manager", "evidence": "FOUND"}]
        result = reconcile_evidence(findings, [], local)
        self.assertEqual(result["items"][0]["status"], "RED")


if __name__ == "__main__":
    unittest.main()
