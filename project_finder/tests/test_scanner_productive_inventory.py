import tempfile
import unittest
from pathlib import Path

from project_finder.scanner import count_scan_files, scan


class ProductiveScannerTests(unittest.TestCase):
    def test_image_assets_are_categorized_and_hashed(self):
        with tempfile.TemporaryDirectory() as tmp:
            asset = Path(tmp) / 'KC-Bilderkasse' / 'pos' / 'assets' / 'apfelpunsch.webp'
            asset.parent.mkdir(parents=True); asset.write_bytes(b'product-image')
            rows = scan([tmp], hash_only_interesting=False)
            row = next(r for r in rows if r.name == 'apfelpunsch.webp')
            self.assertEqual(row.category, 'image_asset'); self.assertTrue(row.sha256); self.assertGreaterEqual(row.score, 45)

    def test_generated_runtime_and_dependency_trees_are_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            keep = root / 'KC-Projekt' / 'src' / 'app.py'; keep.parent.mkdir(parents=True); keep.write_text('print(1)', encoding='utf-8')
            for folder in ('_internal', 'node_modules', '__pycache__', '.venv', 'venv', 'dist', 'build', '.pytest_cache', '.next'):
                p = root / 'KC-Projekt' / folder / 'generated.py'; p.parent.mkdir(parents=True, exist_ok=True); p.write_text('generated', encoding='utf-8')
            rows = scan([tmp], hash_only_interesting=False)
            self.assertEqual([r.name for r in rows], ['app.py'])
            self.assertEqual(count_scan_files([tmp]), 1)

    def test_duplicate_canonical_prefers_non_temp_path(self):
        # Canonical ranking remains independently testable with temp-named files;
        # generated directories themselves are now intentionally pruned.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); temp_copy = root / 'src' / 'app_temp.js'; canonical = root / 'src' / 'app.js'
            temp_copy.parent.mkdir(parents=True); temp_copy.write_text('same-content', encoding='utf-8'); canonical.write_text('same-content', encoding='utf-8')
            rows = scan([tmp], hash_only_interesting=False); by_path = {Path(r.path): r for r in rows}
            self.assertEqual(by_path[canonical].duplicate_of, ''); self.assertEqual(by_path[temp_copy].duplicate_of, str(canonical)); self.assertEqual(by_path[temp_copy].status, 'BLUE')

    def test_scan_is_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'src' / 'keep.py'; source.parent.mkdir(parents=True); source.write_text('print(1)', encoding='utf-8'); before = source.read_bytes()
            scan([tmp], hash_only_interesting=False)
            self.assertTrue(source.exists()); self.assertEqual(source.read_bytes(), before)


if __name__ == '__main__': unittest.main()
