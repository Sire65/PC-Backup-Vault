import json
import tempfile
import unittest
from pathlib import Path

from archive_restore_v198 import _safe_rel
from job_archive_v198 import archive_count, get_job, list_jobs, mark_restore, upsert_job, _local_locator


class DummyStore:
    def __init__(self, root):
        self.path = Path(root) / "config.json"
        self.data = {"cloud_accounts": [], "filesystem_targets": []}


class JobArchiveV198Tests(unittest.TestCase):
    def test_archive_upsert_keeps_unique_job_and_restore_state(self):
        with tempfile.TemporaryDirectory() as td:
            store = DummyStore(td)
            upsert_job(store, {
                "job_id": "job-1", "status": "SUCCESS", "reported_at": "2026-09-08T20:00:00+02:00",
                "source_label": "Quelle", "target_label": "Ziel", "files": 3, "original_bytes": 1234,
                "origin": "LOCAL_REPORT", "locator": {"kind": "FILESYSTEM"},
            })
            mark_restore(store, "job-1", "PASS")
            upsert_job(store, {
                "job_id": "job-1", "status": "SUCCESS", "reported_at": "2026-09-08T20:01:00+02:00",
                "source_label": "Quelle neu", "target_label": "Ziel", "files": 4, "original_bytes": 2222,
                "origin": "LOCAL_REPORT", "locator": {"kind": "FILESYSTEM"},
            })
            self.assertEqual(archive_count(store), 1)
            row = get_job(store, "job-1")
            self.assertEqual(row["file_count"], 4)
            self.assertEqual(row["restore_status"], "PASS")
            self.assertEqual(row["locator"]["kind"], "FILESYSTEM")

    def test_hidrive_locator_matches_configured_account(self):
        with tempfile.TemporaryDirectory() as td:
            store = DummyStore(td)
            store.data["cloud_accounts"] = [{"id": "a1", "name": "Strato_sire25"}]
            locator = _local_locator(store, {
                "target_label": "STRATO HiDrive · Strato_sire25", "backend_label": "STRATO HiDrive"
            })
            self.assertEqual(locator["kind"], "HIDRIVE")
            self.assertEqual(locator["account_id"], "a1")

    def test_archive_is_sorted_newest_first(self):
        with tempfile.TemporaryDirectory() as td:
            store = DummyStore(td)
            for jid, stamp in (("old", "2026-09-08T18:00:00+02:00"), ("new", "2026-09-08T21:00:00+02:00")):
                upsert_job(store, {"job_id": jid, "status": "SUCCESS", "reported_at": stamp, "origin": "TEST"})
            self.assertEqual([r["job_id"] for r in list_jobs(store)], ["new", "old"])

    def test_restore_path_cannot_escape_destination(self):
        rel = _safe_rel(r"L:\\Köcheclub\\Unterordner", "Datei.docx")
        self.assertFalse(rel.is_absolute())
        self.assertNotIn("..", rel.parts)
        self.assertEqual(rel.name, "Datei.docx")


if __name__ == "__main__":
    unittest.main()
