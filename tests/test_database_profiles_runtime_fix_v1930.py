import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database_profiles_runtime_fix_v1930 import looks_like_postgres_dsn, prepare_supabase_test


class Var:
    def __init__(self, value=""):
        self.value = value
    def get(self):
        return self.value
    def set(self, value):
        self.value = value


class Store:
    def __init__(self, profile, stored=""):
        self.profile = profile
        self.stored = stored
        self.saved = None
        self.updated = None
    def get_dsn(self, _pid):
        return self.stored
    def set_dsn(self, _pid, dsn):
        self.saved = dsn
        self.stored = dsn
    def update_profile(self, _pid, values):
        self.updated = dict(values)
        self.profile.update(values)


class Window:
    def __init__(self, profile, value="", stored=""):
        self.profile = profile
        self.vars = {"dsn": Var(value)}
        self.store = Store(profile, stored)
    def selected_profile(self):
        return self.profile


class SupabaseRuntimeFixTests(unittest.TestCase):
    def profile(self):
        return {
            "id": "p1",
            "provider": "supabase",
            "project_ref": "abc123",
            "db_host": "db.abc123.supabase.co",
            "database": "postgres",
            "enabled": True,
        }

    def test_detects_full_dsn(self):
        self.assertTrue(looks_like_postgres_dsn("host=db.example user=postgres dbname=postgres password=x"))
        self.assertTrue(looks_like_postgres_dsn("postgresql://postgres:x@db.example/postgres"))
        self.assertFalse(looks_like_postgres_dsn("mein-normales-db-passwort"))

    def test_plain_password_is_converted_and_saved_only_as_dsn(self):
        w = Window(self.profile(), "Geheim 123!")
        handled, mode = prepare_supabase_test(w)
        self.assertTrue(handled)
        self.assertEqual("password", mode)
        self.assertIn("host='db.abc123.supabase.co'", w.vars["dsn"].get())
        self.assertIn("sslmode=require", w.vars["dsn"].get())
        self.assertEqual(w.vars["dsn"].get(), w.store.saved)
        self.assertNotEqual("Geheim 123!", w.store.saved)

    def test_existing_full_dsn_is_not_rewritten(self):
        dsn = "host=db.example user=postgres dbname=postgres password=x sslmode=require"
        w = Window(self.profile(), dsn)
        handled, mode = prepare_supabase_test(w)
        self.assertTrue(handled)
        self.assertEqual("dsn", mode)
        self.assertIsNone(w.store.saved)
        self.assertEqual(dsn, w.vars["dsn"].get())

    def test_stored_dsn_is_loaded_when_field_is_empty(self):
        dsn = "host=db.example user=postgres dbname=postgres password=x sslmode=require"
        w = Window(self.profile(), "", stored=dsn)
        handled, mode = prepare_supabase_test(w)
        self.assertTrue(handled)
        self.assertEqual("stored", mode)
        self.assertEqual(dsn, w.vars["dsn"].get())

    def test_missing_password_is_reported_without_crash(self):
        w = Window(self.profile(), "", stored="")
        handled, mode = prepare_supabase_test(w)
        self.assertTrue(handled)
        self.assertEqual("missing", mode)

    def test_other_provider_is_untouched(self):
        p = self.profile(); p["provider"] = "neon"
        w = Window(p, "anything")
        handled, mode = prepare_supabase_test(w)
        self.assertFalse(handled)
        self.assertEqual("other-provider", mode)


class AppIntegrationSourceTest(unittest.TestCase):
    def test_app_applies_both_supabase_layers(self):
        source = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn("apply_database_profiles_v1929", source)
        self.assertIn("apply_database_profiles_runtime_fix_v1930", source)
        self.assertIn("apply_database_profiles_v1929(App, SettingsWindow, StorageCenterWindow)", source)
        self.assertIn("apply_database_profiles_runtime_fix_v1930(SettingsWindow)", source)


if __name__ == "__main__":
    unittest.main()
