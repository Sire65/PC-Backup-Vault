import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from database_profiles_v1929 import SUPABASE_PROJECTS, ensure_supabase_profiles, build_supabase_dsn


class FakeStore:
    def __init__(self, profiles=None):
        self.data = {"profiles": list(profiles or []), "active_profile_id": None}
        self._next = 0
        self.saved = 0

    def add_profile(self, profile):
        self._next += 1
        row = dict(profile)
        row["id"] = row.get("id") or f"p{self._next}"
        self.data["profiles"].append(row)
        if not self.data.get("active_profile_id"):
            self.data["active_profile_id"] = row["id"]
        self.save()
        return row["id"]

    def get_profile(self, pid):
        return next((p for p in self.data["profiles"] if p.get("id") == pid), None)

    def save(self):
        self.saved += 1

    def get_dsn(self, pid):
        return None


class DatabaseProfilesV1929Tests(unittest.TestCase):
    def test_seeds_both_supabase_projects_without_secrets(self):
        store = FakeStore()
        rows = ensure_supabase_profiles(store)
        self.assertEqual(2, len(rows))
        refs = {p["project_ref"] for p in store.data["profiles"]}
        self.assertEqual({p["project_ref"] for p in SUPABASE_PROJECTS}, refs)
        for row in store.data["profiles"]:
            self.assertEqual("supabase", row["provider"])
            self.assertEqual("postgres", row["database"])
            self.assertTrue(row["db_host"].startswith("db."))
            self.assertNotIn("password", row)
            self.assertNotIn("dsn", row)

    def test_seed_is_idempotent(self):
        store = FakeStore()
        ensure_supabase_profiles(store)
        ensure_supabase_profiles(store)
        self.assertEqual(2, len(store.data["profiles"]))

    def test_existing_project_is_repaired_not_duplicated(self):
        ref = SUPABASE_PROJECTS[0]["project_ref"]
        store = FakeStore([{
            "id": "old",
            "name": "Mein eigener Name",
            "provider": "postgresql",
            "database": "",
            "project_ref": ref,
            "enabled": False,
        }])
        ensure_supabase_profiles(store)
        matches = [p for p in store.data["profiles"] if p.get("project_ref") == ref]
        self.assertEqual(1, len(matches))
        self.assertEqual("Mein eigener Name", matches[0]["name"])
        self.assertEqual("supabase", matches[0]["provider"])
        self.assertEqual("postgres", matches[0]["database"])
        self.assertTrue(matches[0]["enabled"])
        self.assertTrue(matches[0]["db_host"])

    def test_dsn_uses_project_host_ssl_and_escapes_password(self):
        profile = {
            "project_ref": "abc123",
            "db_host": "db.abc123.supabase.co",
            "database": "postgres",
        }
        dsn = build_supabase_dsn(profile, "a b'c")
        self.assertIn("host='db.abc123.supabase.co'", dsn)
        self.assertIn("port=5432", dsn)
        self.assertIn("dbname='postgres'", dsn)
        self.assertIn("user=postgres", dsn)
        self.assertIn("sslmode=require", dsn)
        self.assertIn("connect_timeout=10", dsn)
        self.assertIn("password=", dsn)

    def test_dsn_requires_password(self):
        with self.assertRaises(ValueError):
            build_supabase_dsn({"project_ref": "x", "db_host": "db.x.supabase.co"}, "")


if __name__ == "__main__":
    unittest.main()
