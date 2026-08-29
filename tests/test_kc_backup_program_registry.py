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

    def test_duplicate_program_id_is_rejected(self):
        program = KCProgramDefinition(program_id="x", display_name="X")
        registry = KCProgramRegistry([program])
        with self.assertRaises(ValueError):
            registry.register(program)


if __name__ == "__main__":
    unittest.main()
