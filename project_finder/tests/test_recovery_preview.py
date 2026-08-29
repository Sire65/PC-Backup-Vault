import tempfile
import unittest
from pathlib import Path

from project_finder.github_compare import compare_item
from project_finder.recovery_preview import build_recovery_preview
from project_finder.scanner import scan


class RecoveryPreviewTests(unittest.TestCase):
    def test_local_only_becomes_grouped_branch_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'DP2'; root.mkdir()
            src = root / 'src'; src.mkdir()
            file = src / 'app.py'; file.write_text('print(42)', encoding='utf-8')
            item = scan([root], hash_only_interesting=False)[0]
            row = compare_item(item, {}, 'Sire65/Dienstplan', verify_content=False)
            preview = build_recovery_preview([item], {'items': [row]})
            self.assertTrue(preview['read_only'])
            self.assertFalse(preview['branch_created'])
            self.assertEqual(preview['candidate_count'], 1)
            self.assertEqual(preview['groups'][0]['repo'], 'Sire65/Dienstplan')
            self.assertEqual(preview['groups'][0]['files'][0]['repo_path'], 'src/app.py')
            self.assertTrue(preview['groups'][0]['proposed_branch'].startswith('recovery/project-finder-dienstplan-'))

    def test_changed_source_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'DP2'; root.mkdir()
            file = root / 'app.py'; file.write_text('old', encoding='utf-8')
            item = scan([root], hash_only_interesting=False)[0]
            row = compare_item(item, {}, 'Sire65/Dienstplan', verify_content=False)
            file.write_text('new', encoding='utf-8')
            preview = build_recovery_preview([item], {'items': [row]})
            self.assertEqual(preview['candidate_count'], 0)
            self.assertEqual(preview['blocked_count'], 1)
            self.assertIn('source_changed_since_compare', preview['blocked'][0]['block_reasons'])


if __name__ == '__main__':
    unittest.main()
