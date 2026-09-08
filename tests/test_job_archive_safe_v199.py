import tempfile
import unittest
from pathlib import Path

import job_archive_safe_v199 as archive


class DummyStore:
    def __init__(self, root):
        self.path = Path(root) / "config.json"
        self.data = {"cloud_accounts": [], "filesystem_targets": []}


class JobArchiveSafeV199Tests(unittest.TestCase):
    def test_refresh_does_not_delete_file_catalog_or_restore_history(self):
        with tempfile.TemporaryDirectory() as td:
            store = DummyStore(td)
            archive.upsert_job(store, {"job_id":"j1","status":"SUCCESS","origin":"TEST","locator":{"kind":"HIDRIVE"}})
            manifest = {"files":[{"name":"enc-name","path":"enc-path","sha256":"a"*64,"original_size":10,"chunks":[{"bytes":20}]}]}
            archive.index_manifest(store, "j1", manifest, "STRATO HiDrive")
            archive.record_restore_event(store, "j1", "PASS", "C:/restore", 1, 10, "PASS", "ok")
            self.assertEqual(archive.archive_file_count(store, "j1"), 1)
            archive.upsert_job(store, {"job_id":"j1","status":"SUCCESS","origin":"TEST","source_label":"neu","locator":{"kind":"HIDRIVE"}})
            self.assertEqual(archive.archive_file_count(store, "j1"), 1)
            self.assertEqual(archive.get_job(store, "j1")["restore_status"], "PASS")


if __name__ == "__main__":
    unittest.main()
