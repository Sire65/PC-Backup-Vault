import tempfile
import unittest
from pathlib import Path

from project_finder.scanner import scan


class ProductiveScannerTests(unittest.TestCase):
    def test_image_assets_are_categorized_and_hashed(self):
        with tempfile.TemporaryDirectory() as tmp:
            asset = Path(tmp) / 'KC-Bilderkasse' / 'pos' / 'assets' / 'apfelpunsch.webp'
            asset.parent.mkdir(parents=True)
            asset.write_bytes(b'product-image')
            rows = scan([tmp], hash_only_interesting=False)
            row = next(r for r in rows if r.name == 'apfelpunsch.webp')
            self.assertEqual(row.category, 'image_asset')
            self.assertTrue(row.sha256)
            self.assertGreaterEqual(row.score, 45)

    def test_duplicate_canonical_prefers_non_temp_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            temp_copy = root / 'build' / 'app.js'
            canonical = root / 'src' / 'app.js'
            temp_copy.parent.mkdir(parents=True)
            canonical.parent.mkdir(parents=True)
            temp_copy.write_text('same-content', encoding='utf-8')
            canonical.write_text('same-content', encoding='utf-8')
            rows = scan([tmp], hash_only_interesting=False)
            by_path = {Path(r.path): r for r in rows}
            self.assertEqual(by_path[canonical].duplicate_of, '')
            self.assertEqual(by_path[temp_copy].duplicate_of, str(canonical))
            self.assertEqual(by_path[temp_copy].status, 'BLUE')

    def test_scan_is_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'src' / 'keep.py'
            source.parent.mkdir(parents=True)
            source.write_text('print(1)', encoding='utf-8')
            before = source.read_bytes()
            scan([tmp], hash_only_interesting=False)
            self.assertTrue(source.exists())
            self.assertEqual(source.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
