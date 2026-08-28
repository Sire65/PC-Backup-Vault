import unittest

from project_finder.incremental_chat_merge import merge_findings


class IncrementalChatMergeTests(unittest.TestCase):
    def test_repeated_export_does_not_duplicate_old_finding(self):
        old = [{"conversation_id": "c1", "timestamp": 1, "text": "DP2 Fehleranalyse fehlt"}]
        current = [
            {"conversation_id": "c1", "timestamp": 1, "text": "DP2 Fehleranalyse fehlt"},
            {"conversation_id": "c1", "timestamp": 2, "text": "DP2 Fehleranalyse repariert"},
        ]
        result = merge_findings(old, current)
        self.assertEqual(result["counts"]["merged"], 2)
        self.assertEqual(result["counts"]["new"], 1)

    def test_same_text_in_different_conversations_is_kept(self):
        old = [{"conversation_id": "c1", "timestamp": 1, "text": "Bitte weiter"}]
        current = [{"conversation_id": "c2", "timestamp": 1, "text": "Bitte weiter"}]
        result = merge_findings(old, current)
        self.assertEqual(result["counts"]["merged"], 2)
        self.assertEqual(result["counts"]["new"], 1)


if __name__ == "__main__":
    unittest.main()
