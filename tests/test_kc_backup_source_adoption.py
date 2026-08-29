import os
import tempfile
import unittest
from pathlib import Path

from kc_backup_program_registry import (
    BackupSourceDefinition,
    KCProgramDefinition,
    KCProgramRegistry,
    SourceKind,
)
from kc_backup_source_adoption import prepare_candidate_adoption
from kc_backup_source_discovery import SourceCandidate


class SourceAdoptionTests(unittest.TestCase):
    def test_valid_folder_candidate_is_prepared_without_mutating_original_registry(self):
        with tempfile.TemporaryDirectory() as tmp:
            source_dir = Path(tmp) / "KC-DP2"
            source_dir.mkdir()
            program = KCProgramDefinition(
                program_id="kc-dp2",
                display_name="KC DP2",
                sources=(BackupSourceDefinition("program", "Programm", SourceKind.FOLDER),),
            )
            registry = KCProgramRegistry([program])
            candidate = SourceCandidate("kc-dp2", "program", source_dir, 90, "Test")

            updated, preview = prepare_candidate_adoption(registry, candidate)

            self.assertIsNone(registry.get("kc-dp2").sources[0].configured_path)
            self.assertEqual(updated.get("kc-dp2").sources[0].configured_path, str(source_dir))
            self.assertTrue(preview.source_ok)
            self.assertTrue(preview.program_ready_after)

    def test_valid_single_source_can_leave_other_required_source_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            source_dir = Path(tmp) / "KC-Futura"
            source_dir.mkdir()
            program = KCProgramDefinition(
                program_id="kc-futura",
                display_name="KC Futura",
                sources=(
                    BackupSourceDefinition("program", "Programm", SourceKind.FOLDER),
                    BackupSourceDefinition("cloud-export", "Cloud Export", SourceKind.DATABASE_EXPORT),
                ),
            )
            registry = KCProgramRegistry([program])
            candidate = SourceCandidate("kc-futura", "program", source_dir, 90, "Test")

            _updated, preview = prepare_candidate_adoption(registry, candidate)

            self.assertTrue(preview.source_ok)
            self.assertFalse(preview.program_ready_after)
            self.assertTrue(any("Cloud Export" in item for item in preview.remaining_blockers))

    def test_missing_candidate_is_rejected(self):
        program = KCProgramDefinition(
            program_id="kc-inventar",
            display_name="KC Inventar",
            sources=(BackupSourceDefinition("program", "Programm", SourceKind.FOLDER),),
        )
        registry = KCProgramRegistry([program])
        candidate = SourceCandidate("kc-inventar", "program", Path("/definitely/missing/kc-source"), 90, "Test")
        with self.assertRaises(ValueError):
            prepare_candidate_adoption(registry, candidate)

    def test_file_is_rejected_for_folder_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "kc-inventar.json"
            file_path.write_text("{}", encoding="utf-8")
            program = KCProgramDefinition(
                program_id="kc-inventar",
                display_name="KC Inventar",
                sources=(BackupSourceDefinition("program", "Programm", SourceKind.FOLDER),),
            )
            registry = KCProgramRegistry([program])
            candidate = SourceCandidate("kc-inventar", "program", file_path, 90, "Test")
            with self.assertRaises(ValueError):
                prepare_candidate_adoption(registry, candidate)

    @unittest.skipUnless(hasattr(os, "symlink"), "Symlinks not supported")
    def test_symlink_candidate_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            real = root / "real"
            real.mkdir()
            link = root / "link"
            try:
                link.symlink_to(real, target_is_directory=True)
            except OSError:
                self.skipTest("Symlink creation not permitted")
            program = KCProgramDefinition(
                program_id="kc-dp2",
                display_name="KC DP2",
                sources=(BackupSourceDefinition("program", "Programm", SourceKind.FOLDER),),
            )
            registry = KCProgramRegistry([program])
            candidate = SourceCandidate("kc-dp2", "program", link, 90, "Test")
            with self.assertRaises(ValueError):
                prepare_candidate_adoption(registry, candidate)

    def test_unknown_source_id_is_rejected(self):
        program = KCProgramDefinition(
            program_id="kc-dp2",
            display_name="KC DP2",
            sources=(BackupSourceDefinition("program", "Programm", SourceKind.FOLDER),),
        )
        registry = KCProgramRegistry([program])
        candidate = SourceCandidate("kc-dp2", "missing-source", Path.cwd(), 90, "Test")
        with self.assertRaises(ValueError):
            prepare_candidate_adoption(registry, candidate)


if __name__ == "__main__":
    unittest.main()
