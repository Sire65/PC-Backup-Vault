import unittest

from project_finder.incremental_chat_merge import merge_findings


class IncrementalChatMergeTests(unittest.TestCase):
    def test_repeated_export_does_not_duplicate_old_finding(self):
        old = [{"conversation_id": "c1", "timestamp": 1, "text": "DP2 Fehleranalyse fehlt", "kind": "OPEN_OR_ERROR"}]
        current = [
            {"conversation_id": "c1", "timestamp": 1, "text": "DP2 Fehleranalyse fehlt", "kind": "OPEN_OR_ERROR"},
            {"conversation_id": "c1", "timestamp": 2, "text": "DP2 Fehleranalyse repariert", "kind": "IMPLEMENTATION_CLAIM"},
        ]
        result = merge_findings(old, current)
        self.assertEqual(result["counts"]["merged"], 2)
        self.assertEqual(result["counts"]["new"], 1)

    def test_same_text_in_different_conversations_is_kept(self):
        old = [{"conversation_id": "c1", "timestamp": 1, "text": "Bitte weiter", "kind": "IDEA_OR_REQUIREMENT"}]
        current = [{"conversation_id": "c2", "timestamp": 1, "text": "Bitte weiter", "kind": "IDEA_OR_REQUIREMENT"}]
        result = merge_findings(old, current)
        self.assertEqual(result["counts"]["merged"], 2)
        self.assertEqual(result["counts"]["new"], 1)

    def test_same_message_id_survives_text_redaction_change(self):
        old = [{
            "conversation_id": "c1", "message_id": "m1", "timestamp": 1,
            "text": "Kontakt max@example.org", "kind": "IDEA_OR_REQUIREMENT",
        }]
        current = [{
            "conversation_id": "c1", "message_id": "m1", "timestamp": 1,
            "text": "Kontakt [EMAIL]", "kind": "IDEA_OR_REQUIREMENT",
        }]
        result = merge_findings(old, current)
        self.assertEqual(result["counts"]["merged"], 1)
        self.assertEqual(result["counts"]["new"], 0)

    def test_one_message_can_keep_multiple_evidence_kinds(self):
        current = [
            {"conversation_id": "c1", "message_id": "m1", "timestamp": 1, "text": "DP2 Fehler muss repariert werden", "kind": "OPEN_OR_ERROR"},
            {"conversation_id": "c1", "message_id": "m1", "timestamp": 1, "text": "DP2 Fehler muss repariert werden", "kind": "IDEA_OR_REQUIREMENT"},
        ]
        result = merge_findings([], current)
        self.assertEqual(result["counts"]["merged"], 2)
        self.assertEqual(result["counts"]["new"], 2)


if __name__ == "__main__":
    unittest.main()
