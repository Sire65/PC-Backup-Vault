import tempfile
import unittest
from pathlib import Path

from kc_backup_program_registry import default_registry
from kc_backup_source_discovery import candidates_for, discover_candidates


class KCBackupSourceDiscoveryTests(unittest.TestCase):
    def test_finds_program_folder_and_export_without_mutating_registry(self):
        registry = default_registry()
        before = {
            (p.program_id, s.source_id): s.configured_path
            for p in registry.all()
            for s in p.sources
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dp2 = root / "KC-DP2"
            dp2.mkdir()
            export = root / "KC-DP2-Daten-Export.json"
            export.write_text("{}", encoding="utf-8")

            found = discover_candidates(root, registry.all(), max_depth=2)
            self.assertTrue(any(c.program_id == "kc-dp2" and c.path == dp2 for c in found))
            self.assertTrue(any(c.program_id == "kc-dp2" and c.path == export for c in found))

        after = {
            (p.program_id, s.source_id): s.configured_path
            for p in registry.all()
            for s in p.sources
        }
        self.assertEqual(before, after)

    def test_pc_backup_vault_folder_is_discoverable(self):
        registry = default_registry()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            vault = root / "PC-Backup-Vault"
            vault.mkdir()
            found = discover_candidates(root, registry.all(), max_depth=1)
            self.assertTrue(any(c.program_id == "pc-backup-vault" and c.source_id == "program" and c.path == vault for c in found))

    def test_raw_database_files_are_never_suggested_as_exports(self):
        registry = default_registry()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw_db = root / "KC-DP2-Daten-Export.sqlite"
            raw_db.write_bytes(b"not-a-safe-export")
            found = discover_candidates(root, registry.all(), max_depth=1)
            self.assertFalse(any(c.path == raw_db for c in found))

    def test_low_confidence_unrelated_paths_are_ignored(self):
        registry = default_registry()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Urlaub").mkdir()
            (root / "notizen.txt").write_text("x", encoding="utf-8")
            found = discover_candidates(root, registry.all(), max_depth=1)
            self.assertEqual(found, [])

    def test_build_and_git_directories_are_skipped(self):
        registry = default_registry()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hidden = root / ".git"
            hidden.mkdir()
            (hidden / "KC-DP2").mkdir()
            build = root / "build"
            build.mkdir()
            (build / "KC-Verwaltung").mkdir()
            found = discover_candidates(root, registry.all(), max_depth=3)
            self.assertEqual(found, [])

    def test_candidates_for_filters_exact_program_and_source(self):
        registry = default_registry()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "KC-DP2").mkdir()
            found = discover_candidates(root, registry.all(), max_depth=1)
            selected = candidates_for(found, "kc-dp2", "program")
            self.assertTrue(selected)
            self.assertTrue(all(c.program_id == "kc-dp2" and c.source_id == "program" for c in selected))

    def test_invalid_root_is_rejected(self):
        registry = default_registry()
        with self.assertRaises(ValueError):
            discover_candidates(Path("/definitely/not/existing/kc-source-root"), registry.all())


if __name__ == "__main__":
    unittest.main()
