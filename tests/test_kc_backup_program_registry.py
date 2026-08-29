import tempfile
import unittest
from pathlib import Path

from kc_backup_program_registry import (
    BackupSourceDefinition,
    KCProgramDefinition,
    KCProgramRegistry,
    SourceKind,
    SourceRequirement,
    default_registry,
    resolve_program_scope,
)


class KCProgramRegistryTests(unittest.TestCase):
    def test_default_registry_contains_managed_programs(self):
        registry = default_registry()
        self.assertEqual(
            {p.program_id for p in registry.all()},
            {
                "pc-backup-vault",
                "kc-dp2",
                "kc-verwaltung",
                "kc-marktkasse",
                "kc-futura",
                "kc-tv-editor",
                "kc-inventar",
                "kc-bilderrechner",
            },
        )

    def test_templates_are_not_ready_until_real_sources_are_configured(self):
        registry = default_registry()
        for program in registry.all():
            self.assertFalse(program.ready)
            self.assertTrue(program.missing_required_sources())
            self.assertEqual(program.configured_sources(), ())

    def test_every_default_program_has_at_least_one_required_source(self):
        registry = default_registry()
        for program in registry.all():
            self.assertTrue(program.required_sources(), program.program_id)

    def test_pc_backup_vault_has_no_guessed_source(self):
        program = default_registry().get("pc-backup-vault")
        self.assertFalse(program.ready)
        self.assertTrue(any(s.source_id == "program" for s in program.required_sources()))
        self.assertEqual(program.configured_sources(), ())

    def test_missing_required_source_blocks_scope(self):
        program = KCProgramDefinition(
            program_id="x",
            display_name="X",
            sources=(
                BackupSourceDefinition("required", "Pflicht", SourceKind.FOLDER),
                BackupSourceDefinition("optional", "Optional", SourceKind.DOCUMENTS, SourceRequirement.OPTIONAL),
            ),
        )
        scope = resolve_program_scope(program)
        self.assertFalse(scope.ready)
        self.assertTrue(any("Pflichtbereich" in item for item in scope.blockers))

    def test_existing_required_source_makes_scope_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            program = KCProgramDefinition(
                program_id="x",
                display_name="X",
                sources=(
                    BackupSourceDefinition("required", "Pflicht", SourceKind.FOLDER, configured_path=tmp),
                ),
            )
            scope = resolve_program_scope(program)
            self.assertTrue(scope.ready)
            self.assertEqual(scope.paths, (Path(tmp),))

    def test_missing_optional_source_warns_but_does_not_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            program = KCProgramDefinition(
                program_id="x",
                display_name="X",
                sources=(
                    BackupSourceDefinition("required", "Pflicht", SourceKind.FOLDER, configured_path=tmp),
                    BackupSourceDefinition("optional", "Optional", SourceKind.DOCUMENTS, SourceRequirement.OPTIONAL),
                ),
            )
            scope = resolve_program_scope(program)
            self.assertTrue(scope.ready)
            self.assertEqual(len(scope.warnings), 1)

    def test_raw_sqlite_as_required_export_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw_db = Path(tmp) / "live.sqlite"
            raw_db.write_bytes(b"sqlite")
            program = KCProgramDefinition(
                program_id="x",
                display_name="X",
                sources=(
                    BackupSourceDefinition(
                        "cloud-export", "Cloud Export", SourceKind.DATABASE_EXPORT, configured_path=str(raw_db)
                    ),
                ),
            )
            scope = resolve_program_scope(program)
            self.assertFalse(scope.ready)
            self.assertEqual(scope.paths, ())
            self.assertTrue(any("Rohdatenbanken" in blocker for blocker in scope.blockers))

    def test_file_configured_for_folder_source_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "not-a-folder.json"
            file_path.write_text("{}", encoding="utf-8")
            program = KCProgramDefinition(
                program_id="x",
                display_name="X",
                sources=(
                    BackupSourceDefinition("program", "Programm", SourceKind.FOLDER, configured_path=str(file_path)),
                ),
            )
            scope = resolve_program_scope(program)
            self.assertFalse(scope.ready)
            self.assertTrue(any("Ordner erwartet" in blocker for blocker in scope.blockers))

    def test_safe_json_export_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            export = Path(tmp) / "kc-data-export.json"
            export.write_text("{}", encoding="utf-8")
            program = KCProgramDefinition(
                program_id="x",
                display_name="X",
                sources=(
                    BackupSourceDefinition("data", "Daten Export", SourceKind.LOCAL_EXPORT, configured_path=str(export)),
                ),
            )
            scope = resolve_program_scope(program)
            self.assertTrue(scope.ready)
            self.assertEqual(scope.paths, (export,))

    def test_wrong_optional_type_warns_without_becoming_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            required = root / "program"
            required.mkdir()
            wrong_optional = root / "documents.txt"
            wrong_optional.write_text("x", encoding="utf-8")
            program = KCProgramDefinition(
                program_id="x",
                display_name="X",
                sources=(
                    BackupSourceDefinition("required", "Programm", SourceKind.FOLDER, configured_path=str(required)),
                    BackupSourceDefinition(
                        "documents", "Dokumente", SourceKind.DOCUMENTS, SourceRequirement.OPTIONAL,
                        configured_path=str(wrong_optional),
                    ),
                ),
            )
            scope = resolve_program_scope(program)
            self.assertTrue(scope.ready)
            self.assertEqual(scope.paths, (required,))
            self.assertTrue(any("Ordner erwartet" in warning for warning in scope.warnings))

    def test_duplicate_program_id_is_rejected(self):
        program = KCProgramDefinition(program_id="x", display_name="X")
        registry = KCProgramRegistry([program])
        with self.assertRaises(ValueError):
            registry.register(program)


if __name__ == "__main__":
    unittest.main()
