import unittest

from project_finder.chat_inventory import analyze_conversation
from project_finder.chat_safety import redact_text, safe_source_label


class ChatSafetyTests(unittest.TestCase):
    def test_redacts_common_sensitive_values(self):
        text = "Mail max@example.org Telefon +49 170 1234567 password=geheim sk-abcdefghijklmnop"
        cleaned = redact_text(text)
        self.assertNotIn("max@example.org", cleaned)
        self.assertNotIn("1234567", cleaned)
        self.assertNotIn("geheim", cleaned)
        self.assertNotIn("sk-abcdefghijklmnop", cleaned)

    def test_source_path_anonymized_by_default(self):
        self.assertEqual(safe_source_label(r"C:\Users\Max\Downloads\export.zip"), "export.zip")
        self.assertEqual(safe_source_label("/home/max/Downloads/export.zip"), "export.zip")

    def test_message_role_and_id_are_preserved_as_evidence(self):
        conv = {
            "id": "c1",
            "title": "DP2 Entwicklung",
            "mapping": {
                "n1": {
                    "message": {
                        "id": "m1",
                        "author": {"role": "user"},
                        "create_time": 123,
                        "content": {"parts": ["DP2 Fehler geht nicht"]},
                    }
                }
            },
        }
        result = analyze_conversation(conv)
        self.assertTrue(result["findings"])
        finding = result["findings"][0]
        self.assertEqual(finding["message_id"], "m1")
        self.assertEqual(finding["role"], "user")

    def test_one_message_can_produce_more_than_one_kind(self):
        conv = {
            "id": "c2",
            "title": "DP2",
            "mapping": {
                "n1": {"message": {"id": "m2", "author": {"role": "user"}, "content": {"parts": ["DP2 Fehler geht nicht, muss noch eingebaut werden"]}}}
            },
        }
        result = analyze_conversation(conv)
        kinds = {x["kind"] for x in result["findings"]}
        self.assertIn("OPEN_OR_ERROR", kinds)
        self.assertIn("IDEA_OR_REQUIREMENT", kinds)


if __name__ == "__main__":
    unittest.main()
