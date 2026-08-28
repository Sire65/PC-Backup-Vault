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

    def test_exact_chat_source_is_preserved_for_audit(self):
        findings = [{
            "project": "KC Verwaltung", "kind": "IDEA_OR_REQUIREMENT", "text": "Mitgliederfilter ergänzen",
            "conversation_id": "conv-17", "message_id": "msg-44", "title": "Verwaltung", "timestamp": 12345,
            "evidence_strength": "HIGH",
        }]
        result = reconcile_evidence(findings, [])
        self.assertEqual(result["schema"], "pc-backup-vault.evidence-reconciliation.v2")
        self.assertTrue(result["trust"]["source_traceability"])
        source = result["details"][0]["source"]
        self.assertEqual(source["conversation_id"], "conv-17")
        self.assertEqual(source["message_id"], "msg-44")
        self.assertEqual(source["title"], "Verwaltung")
        self.assertEqual(result["details"][0]["requirement"], "Mitgliederfilter ergänzen")


if __name__ == "__main__":
    unittest.main()
