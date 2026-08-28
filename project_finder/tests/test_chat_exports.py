import json
import tempfile
import unittest
from pathlib import Path

from project_finder.chat_exports import build_chat_summary, build_requirements, write_analysis_bundle


class ChatExportsTests(unittest.TestCase):
    def setUp(self):
        self.inventory = {
            "source": "export.zip",
            "conversation_count": 3,
            "selected_count": 2,
            "classifications": {"development": 1, "possible_development": 1, "other": 1},
            "projects": {"DP2 / Dienstplan": {"ideas": 1, "implementation_claims": 0, "open_or_error": 0, "rejected": 0}},
            "privacy": {"redaction_enabled": True, "source_path_anonymized": True, "raw_chat_upload_required": False},
            "rule": "technical proof required",
            "findings": [{
                "conversation_id": "c1", "message_id": "m1", "role": "user", "title": "DP2",
                "timestamp": "1", "project": "DP2 / Dienstplan", "kind": "IDEA_OR_REQUIREMENT",
                "text": "Fehleranalyse erweitern", "evidence_strength": "chat-requirement",
            }],
        }

    def test_summary_excludes_raw_conversations(self):
        summary = build_chat_summary(self.inventory)
        self.assertNotIn("findings", summary)
        self.assertNotIn("conversations", summary)
        self.assertTrue(summary["privacy"]["redaction_enabled"])

    def test_requirements_keep_traceability(self):
        req = build_requirements(self.inventory)
        self.assertEqual(req["count"], 1)
        self.assertEqual(req["requirements"][0]["message_id"], "m1")

    def test_bundle_never_copies_raw_export(self):
        with tempfile.TemporaryDirectory() as td:
            result = write_analysis_bundle(self.inventory, td)
            self.assertFalse(result["raw_chat_export_copied"])
            self.assertTrue(Path(result["summary"]).exists())
            self.assertTrue(Path(result["requirements"]).exists())
            self.assertTrue(Path(result["findings_csv"]).exists())
            payload = json.loads(Path(result["summary"]).read_text(encoding="utf-8"))
            self.assertEqual(payload["source"], "export.zip")


if __name__ == "__main__":
    unittest.main()
