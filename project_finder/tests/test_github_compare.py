import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from project_finder.github_compare import candidate_repo_path, compare_inventory, compare_item
from project_finder.scanner import scan


class GitHubCompareTests(unittest.TestCase):
    def test_candidate_repo_path_strips_project_root(self):
        p = Path('D:/Entwicklung/DP2/src/app.py')
        self.assertEqual(candidate_repo_path(p, 'Sire65/Dienstplan'), 'src/app.py')

    def test_identical_and_divergent_states(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'DP2'; root.mkdir()
            source = root / 'app.py'; source.write_text('print(42)', encoding='utf-8')
            item = scan([root], hash_only_interesting=False)[0]
            index = {'app.py': {'blob_sha': 'abc', 'size': item.size, 'repo': 'Sire65/Dienstplan', 'ref': 'main'}}
            with patch('project_finder.github_compare.fetch_blob_sha256', return_value=item.sha256):
                self.assertEqual(compare_item(item, index, 'Sire65/Dienstplan')['state'], 'IDENTICAL')
            with patch('project_finder.github_compare.fetch_blob_sha256', return_value='0' * 64):
                self.assertEqual(compare_item(item, index, 'Sire65/Dienstplan')['state'], 'DIVERGENT')

    def test_inventory_comparison_is_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'DP2'; root.mkdir()
            source = root / 'app.py'; source.write_text('print(42)', encoding='utf-8'); before = source.read_bytes()
            items = scan([root], hash_only_interesting=False)
            with patch('project_finder.github_compare.fetch_repo_tree', return_value={}):
                report = compare_inventory(items, token='test', verify_content=False)
            self.assertTrue(report['read_only'])
            self.assertEqual(report['counts'].get('LOCAL_ONLY'), 1)
            self.assertEqual(source.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
