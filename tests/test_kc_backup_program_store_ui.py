import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from kc_backup_program_registry import KCProgramRegistry, default_registry, resolve_program_scope
from kc_backup_program_store import load_program_registry, save_program_registry


class KCProgramStoreTests(unittest.TestCase):
    def test_program_source_configuration_roundtrip(self):
        base = default_registry()
        program = base.get("kc-dp2")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            program_dir = root / "dp2"; program_dir.mkdir()
            local_export = root / "dp2-local.json"; local_export.write_text("{}", encoding="utf-8")
            cloud_export = root / "dp2-cloud.json"; cloud_export.write_text("{}", encoding="utf-8")
            configured = replace(
                program,
                sources=tuple(
                    replace(source, configured_path={
                        "program": str(program_dir),
                        "local-data": str(local_export),
                        "cloud-export": str(cloud_export),
                    }.get(source.source_id, source.configured_path))
                    for source in program.sources
                ),
            )
            registry = KCProgramRegistry(configured if p.program_id == configured.program_id else p for p in base.all())
            store = root / "programs.json"
            save_program_registry(store, registry)
            loaded = load_program_registry(store, default_registry())
            loaded_dp2 = loaded.get("kc-dp2")
            self.assertTrue(loaded_dp2.ready)
            scope = resolve_program_scope(loaded_dp2)
            self.assertTrue(scope.ready)
            self.assertEqual(len(scope.paths), 3)
            self.assertTrue(any("Dokumente" in warning for warning in scope.warnings))

    def test_empty_store_does_not_invent_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "programs.json"
            save_program_registry(store, default_registry())
            loaded = load_program_registry(store, default_registry())
            for program in loaded.all():
                self.assertFalse(program.ready)
                self.assertEqual(program.configured_sources(), ())

    def test_unknown_store_version_is_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "programs.json"
            store.write_text('{"store_version":999,"programs":{}}', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_program_registry(store, default_registry())


if __name__ == "__main__":
    unittest.main()
