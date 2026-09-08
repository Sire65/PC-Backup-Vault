import sqlite3
import tempfile
import unittest
from pathlib import Path

from archive_restore_v198 import _safe_rel
from job_archive_v198 import (
    _local_locator, archive_count, archive_file_count, archive_path, get_job,
    index_manifest, ingest_neon_jobs, list_job_files, list_jobs, mark_restore,
    record_restore_event, upsert_job,
)


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

    def test_schema_v2_creates_file_storage_verify_restore_and_event_tables(self):
        with tempfile.TemporaryDirectory() as td:
            store = DummyStore(td)
            upsert_job(store, {"job_id": "j", "status": "SUCCESS", "origin": "TEST"})
            conn = sqlite3.connect(archive_path(store))
            try:
                tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                self.assertTrue({"jobs","job_files","storage_locations","verification_events","restore_events","job_events"}.issubset(tables))
                version = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
                self.assertEqual(version, "2")
            finally:
                conn.close()

    def test_manifest_file_catalog_is_persisted_per_job(self):
        with tempfile.TemporaryDirectory() as td:
            store = DummyStore(td)
            upsert_job(store, {"job_id":"job-files","status":"SUCCESS","origin":"TEST","locator":{"kind":"HIDRIVE"}})
            manifest = {"files":[
                {"name":"ENC-NAME-1","path":"ENC-PATH-1","sha256":"a"*64,"original_size":100,"modified_at":123.0,
                 "chunks":[{"bytes":70},{"bytes":50}]},
                {"name":"ENC-NAME-2","path":"ENC-PATH-2","sha256":"b"*64,"original_size":200,"modified_at":124.0,
                 "chunks":[{"bytes":210}]},
            ]}
            self.assertEqual(index_manifest(store,"job-files",manifest,"STRATO HiDrive"),2)
            self.assertEqual(archive_file_count(store,"job-files"),2)
            files = list_job_files(store,"job-files")
            self.assertEqual(files[0]["job_id"],"job-files")
            self.assertTrue(all(f["name_cipher"].startswith("ENC-") for f in files))
            self.assertEqual(sum(f["chunk_count"] for f in files),3)

    def test_restore_events_keep_history_and_latest_job_state(self):
        with tempfile.TemporaryDirectory() as td:
            store = DummyStore(td)
            upsert_job(store,{"job_id":"restore-job","status":"SUCCESS","origin":"TEST"})
            record_restore_event(store,"restore-job","FAILED","C:/test",details="probe")
            record_restore_event(store,"restore-job","PASS","C:/test",1,123,"PASS","ok")
            self.assertEqual(get_job(store,"restore-job")["restore_status"],"PASS")
            conn=sqlite3.connect(archive_path(store))
            try:
                self.assertEqual(conn.execute("SELECT count(*) FROM restore_events WHERE job_id='restore-job'").fetchone()[0],2)
            finally:
                conn.close()

    def test_hidrive_locator_matches_configured_account(self):
        with tempfile.TemporaryDirectory() as td:
            store = DummyStore(td)
            store.data["cloud_accounts"] = [{"id": "a1", "name": "Strato_sire25"}]
            locator = _local_locator(store, {"job_id":"x","target_label": "STRATO HiDrive · Strato_sire25", "backend_label": "STRATO HiDrive"})
            self.assertEqual(locator["kind"], "HIDRIVE")
            self.assertEqual(locator["account_id"], "a1")

    def test_archive_is_sorted_newest_first(self):
        with tempfile.TemporaryDirectory() as td:
            store = DummyStore(td)
            for jid, stamp in (("old", "2026-09-08T18:00:00+02:00"), ("new", "2026-09-08T21:00:00+02:00")):
                upsert_job(store, {"job_id": jid, "status": "SUCCESS", "reported_at": stamp, "origin": "TEST"})
            self.assertEqual([r["job_id"] for r in list_jobs(store)], ["new", "old"])

    def test_neon_and_b2_jobs_enter_same_archive(self):
        with tempfile.TemporaryDirectory() as td:
            store = DummyStore(td)
            rows = [
                ("b2-job", "2026-09-08T19:00:00+02:00", "2026-09-08T19:01:00+02:00", "SUCCESS", 2,2000,1000,0,"","MANUAL",None,"INCREMENTAL",2,2,0,"B2",1,60,30,50,0,1,1500),
                ("neon-job", "2026-09-08T18:00:00+02:00", "2026-09-08T18:01:00+02:00", "SUCCESS", 1,500,500,0,"","MANUAL",None,"FULL",1,1,0,"NEON",1,60,8,10,0,0,500),
            ]
            count = ingest_neon_jobs(store, "dsn", lambda _dsn, _limit: rows)
            self.assertEqual(count, 2)
            jobs = {r["job_id"]: r for r in list_jobs(store)}
            self.assertEqual(jobs["b2-job"]["target_label"], "Backblaze B2 + Neon-Core")
            self.assertEqual(jobs["neon-job"]["backend_label"], "Neon")
            self.assertEqual(jobs["b2-job"]["backup_mode"], "INCREMENTAL")

    def test_restore_path_cannot_escape_destination(self):
        rel = _safe_rel(r"L:\\Köcheclub\\..\\..\\Windows\\System32", r"..\\Datei.docx")
        self.assertFalse(rel.is_absolute())
        self.assertNotIn("..", rel.parts)
        self.assertEqual(rel.name, "Datei.docx")


if __name__ == "__main__":
    unittest.main()
