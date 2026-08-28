import json
import tempfile
import unittest
from pathlib import Path

from project_finder.scanner import purge_quarantine, quarantine, restore_quarantine


class QuarantineSafetyTests(unittest.TestCase):
    def test_quarantine_is_reversible_and_manifest_has_hash(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); src = root / "source.txt"; src.write_text("abc", encoding="utf-8")
            rows = quarantine([str(src)], str(root / "q"), reason="test")
            self.assertFalse(src.exists())
            self.assertTrue(rows[0]["sha256"])
            manifest = Path(rows[0]["quarantine"]).parent / "manifest.json"
            restored = restore_quarantine(str(manifest))
            self.assertTrue(src.exists())
            self.assertEqual(restored[0]["restored"], str(src))

    def test_purge_requires_confirmation_and_age_gate(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); src = root / "old.txt"; src.write_text("abc", encoding="utf-8")
            rows = quarantine([str(src)], str(root / "q"))
            q = Path(rows[0]["quarantine"]); manifest = q.parent / "manifest.json"
            with self.assertRaises(PermissionError):
                purge_quarantine(str(manifest), min_age_days=0, confirmed=False)
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            when = payload["items"][0]["quarantined_at_epoch"]
            self.assertEqual(purge_quarantine(str(manifest), min_age_days=30, confirmed=True, now=when + 10), [])
            deleted = purge_quarantine(str(manifest), min_age_days=30, confirmed=True, now=when + 31 * 86400)
            self.assertEqual(len(deleted), 1)
            self.assertFalse(q.exists())


if __name__ == "__main__":
    unittest.main()
