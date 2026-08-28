import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from project_finder.chat_inventory import inventory_export
from project_finder.development_center import DevelopmentItem, decide_status


class ChatInventoryTests(unittest.TestCase):
    def test_export_is_classified_and_implementation_claim_is_not_green(self):
        conv = [{
            "id": "c1",
            "title": "DP2 Entwicklung",
            "mapping": {
                "1": {"message": {"content": {"parts": ["Bitte Fehleranalyse reparieren, das muss noch eingebaut werden."]}}},
                "2": {"message": {"content": {"parts": ["DP2 ist fertig und umgesetzt. GitHub Build testen."]}}},
            },
        }]
        with tempfile.TemporaryDirectory() as td:
            z = Path(td) / "export.zip"
            with zipfile.ZipFile(z, "w") as zf:
                zf.writestr("conversations.json", json.dumps(conv))
            inv = inventory_export(str(z))
            self.assertEqual(inv["conversation_count"], 1)
            self.assertEqual(inv["classifications"]["development"], 1)
            claims = [x for x in inv["findings"] if x["kind"] == "IMPLEMENTATION_CLAIM"]
            self.assertTrue(claims)
            self.assertEqual(claims[0]["evidence_strength"], "chat-claim-unverified")

    def test_development_center_requires_technical_evidence_for_green(self):
        item = DevelopmentItem(project="DP2", requirement="Fehleranalyse", chat_claim="IMPLEMENTED")
        self.assertEqual(decide_status(item).status, "YELLOW")
        item.git_evidence = "FOUND"
        item.test_evidence = "PASS"
        # A green Git test alone is not enough until the local-vs-Git relation
        # is known. This prevents overwriting a newer local development state.
        self.assertEqual(decide_status(item).status, "YELLOW")
        item.local_git_relation = "SAME"
        self.assertEqual(decide_status(item).status, "GREEN")

    def test_lost_local_development_is_red(self):
        item = DevelopmentItem(project="KC Manager", requirement="Leitstand", local_evidence="FOUND", git_evidence="MISSING")
        self.assertEqual(decide_status(item).status, "RED")


if __name__ == "__main__":
    unittest.main()
