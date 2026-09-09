import unittest

from storage_center_v1919 import (
    collect_storage_targets, _b2_prefix, _collapse_nested, _hidrive_protected, _b2_list,
)


class Store:
    def __init__(self):
        self.data = {
            "cloud_accounts": [
                {"id":"h1","name":"Strato_hausmeister1","provider_code":"STRATO_HIDRIVE","enabled":True,"username":"hausmeister1"},
                {"id":"h2","name":"Strato_sire25","provider_code":"STRATO_HIDRIVE","enabled":True,"username":"sire25","methods":["SMB"]},
                {"id":"off","name":"Aus","provider_code":"STRATO_HIDRIVE","enabled":False,"username":"off"},
            ],
            "cloud_provider_settings": {},
            "profiles": [
                {"id":"n1","name":"KC Neon","provider":"neon","enabled":True,"database":"kc"},
                {"id":"s1","name":"Academy Supabase","provider":"supabase","enabled":True,"database":"postgres"},
                {"id":"p1","name":"Postgres lokal","provider":"postgresql","enabled":True,"database":"local"},
                {"id":"x1","name":"Ohne DSN","provider":"neon","enabled":True,"database":"x"},
            ],
        }
        self._dsn={"n1":"postgresql://n","s1":"postgresql://s","p1":"postgresql://p"}
    def save(self): pass
    def get_dsn(self,pid): return self._dsn.get(pid)
    def get_b2_runtime_config(self):
        return {"configured":True,"bucket":"kc-backup","prefix":"pc-backup-vault"}


class FakeB2:
    def list_objects_v2(self, **kwargs):
        self.kwargs=kwargs
        return {
            "CommonPrefixes":[{"Prefix":"root/folder/"}],
            "Contents":[
                {"Key":"root/file.txt","Size":12,"LastModified":None},
                {"Key":"root/marker/","Size":0,"LastModified":None},
            ],
        }


class StorageCenterTests(unittest.TestCase):
    def test_registry_collects_two_hidrive_b2_and_database_profiles(self):
        rows=collect_storage_targets(Store())
        labels=[r["label"] for r in rows]
        self.assertIn("HiDrive · Strato_hausmeister1",labels)
        self.assertIn("HiDrive · Strato_sire25",labels)
        self.assertIn("Backblaze B2 · kc-backup",labels)
        self.assertIn("Neon · KC Neon",labels)
        self.assertIn("Supabase · Academy Supabase",labels)
        self.assertIn("PostgreSQL · Postgres lokal",labels)
        self.assertFalse(any("Ohne DSN" in x for x in labels))
        self.assertFalse(any("Aus" in x for x in labels))

    def test_nested_selection_keeps_parent_only(self):
        rows=[
            {"path":"/a","is_dir":True},
            {"path":"/a/b.txt","is_dir":False},
            {"path":"/z.txt","is_dir":False},
        ]
        out=_collapse_nested(rows)
        self.assertEqual([r["path"] for r in out],["/a","/z.txt"])

    def test_protected_hidrive_detects_nested_vault(self):
        self.assertTrue(_hidrive_protected("/users/u/PC_Backup_Vault/.pc-backup-vault/chunks/a.bin"))
        self.assertFalse(_hidrive_protected("/users/u/Documents/a.txt"))

    def test_b2_prefix_is_normalized(self):
        self.assertEqual(_b2_prefix("/root/test/"),"root/test/")
        self.assertEqual(_b2_prefix(""),"")

    def test_b2_direct_listing_builds_virtual_folders_and_objects(self):
        client=FakeB2(); rows=_b2_list(client,"bucket","root")
        self.assertEqual(client.kwargs["Prefix"],"root/")
        self.assertEqual(client.kwargs["Delimiter"],"/")
        self.assertEqual(rows[0]["key"],"root/folder/")
        self.assertTrue(rows[0]["is_dir"])
        self.assertEqual(rows[1]["key"],"root/file.txt")
        self.assertFalse(rows[1]["is_dir"])


if __name__ == "__main__":
    unittest.main()
