import tempfile
import unittest
from pathlib import Path

from storage_center_exact_v1920 import (
    _dsn_database,
    _fs_list,
    _sql_databases,
    collect_storage_targets_v1920,
)


class Store:
    def __init__(self, root):
        self.data = {
            "filesystem_targets": [
                {"id":"nas1","name":"NAS Archiv","path":str(root),"kind":"NAS"},
                {"id":"gone","name":"USB Offline","path":str(root / "missing"),"kind":"LAUFWERK"},
            ],
            "profiles": [
                {"id":"n1","name":"Neon Vault","provider":"neon","enabled":True,"database":"pc_backup_vault","project_ref":"restless-lake"},
                {"id":"s1","name":"Supabase KC","provider":"supabase","enabled":True,"database":"postgres","project_ref":"kc"},
            ],
            "b2": {"enabled":True,"bucket":"all-data","endpoint_url":"https://b2.example","prefix":"pc-backup-vault"},
        }
        self._dsn = {"n1":"postgresql://u:p@example.test/neondb"}
    def get_dsn(self, pid): return self._dsn.get(pid)
    def get_b2_runtime_config(self):
        return {"configured":True,"bucket":"all-data","prefix":"pc-backup-vault"}


def old_collect(store):
    return [
        {"id":"b2:default","kind":"B2","name":"all-data","label":"Backblaze B2 · all-data","prefix":"pc-backup-vault"},
        {"id":"db:n1","kind":"POSTGRES","name":"Neon Vault","label":"Neon · Neon Vault","profile_id":"n1","provider":"neon","database":"pc_backup_vault","project_ref":"restless-lake"},
    ]


class FakeConn:
    def execute(self, _sql):
        return self
    def fetchall(self):
        return [("neondb",),("pc_backup_vault",),("postgres",)]


class ExactStorageCenterTests(unittest.TestCase):
    def test_registry_contains_this_pc_filesystem_and_missing_database_profile(self):
        with tempfile.TemporaryDirectory() as td:
            store=Store(Path(td))
            rows=collect_storage_targets_v1920(store,old_collect)
            by_id={r["id"]:r for r in rows}
            self.assertIn("fs:this-pc",by_id)
            self.assertIn("fs:nas1",by_id)
            self.assertTrue(by_id["fs:nas1"]["ready"])
            self.assertIn("fs:gone",by_id)
            self.assertFalse(by_id["fs:gone"]["ready"])
            self.assertIn("db:s1",by_id)
            self.assertFalse(by_id["db:s1"]["ready"])
            self.assertIn("Zugang fehlt",by_id["db:s1"]["label"])

    def test_b2_explorer_starts_at_real_bucket_root_and_keeps_backup_prefix(self):
        with tempfile.TemporaryDirectory() as td:
            rows=collect_storage_targets_v1920(Store(Path(td)),old_collect)
            b2=next(r for r in rows if r["kind"]=="B2")
            self.assertEqual(b2["prefix"],"")
            self.assertEqual(b2["backup_prefix"],"pc-backup-vault")

    def test_database_dsn_can_be_switched_to_actual_database_node(self):
        dsn=_dsn_database("host=localhost user=test dbname=neondb","pc_backup_vault")
        self.assertIn("dbname=pc_backup_vault",dsn)
        self.assertNotIn("dbname=neondb",dsn)

    def test_database_listing_returns_all_connectable_non_template_databases(self):
        self.assertEqual(_sql_databases(FakeConn()),["neondb","pc_backup_vault","postgres"])

    def test_filesystem_listing_keeps_hidden_items_visible_and_marks_them(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            (root/"normal.txt").write_text("x",encoding="utf-8")
            (root/".hidden").mkdir()
            rows=_fs_list(root)
            names={r["name"]:r for r in rows}
            self.assertIn("normal.txt",names)
            self.assertIn(".hidden",names)
            self.assertTrue(names[".hidden"]["hidden"])
            self.assertTrue(names[".hidden"]["is_dir"])


if __name__ == "__main__":
    unittest.main()
