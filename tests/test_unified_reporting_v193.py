import tempfile
import unittest
from pathlib import Path

from unified_reporting_integration_v193 import _local_as_history_tuple
from unified_reporting_v193 import (
    enrich_result,
    latest_local_job_report,
    list_local_job_reports,
    load_local_job_report,
    persist_local_job_report,
    report_lines,
    target_summary,
)


class DummyStore:
    def __init__(self, root):
        self.path = Path(root) / "config.json"


class UnifiedReportingTests(unittest.TestCase):
    def test_hidrive_assignment_is_explicit(self):
        r = enrich_result(
            {"job_id":"job-1","status":"SUCCESS","provider":"STRATO_HIDRIVE","transport":"SFTP","files":1},
            [Path("Dokuliste Alexander.xlsx")],
            {"name":"Cloud · Strato_sire25","kind":"CLOUD-SFTP","cloud_account_id":"secret-id","path":"/users/sire25/PC_Backup_Vault"},
        )
        self.assertEqual(r["source_label"], "Dokuliste Alexander.xlsx")
        self.assertIn("Strato_sire25", r["target_label"])
        self.assertEqual(r["backend_label"], "STRATO HiDrive")
        self.assertEqual(r["transport_label"], "SFTP")
        self.assertIn("→", r["source_to_target"])
        self.assertEqual(r["directory_count"], 1)

    def test_local_report_contains_source_target_but_no_credentials_or_remote_path(self):
        with tempfile.TemporaryDirectory() as td:
            store = DummyStore(td)
            r = persist_local_job_report(
                store,
                {"job_id":"job-2","status":"SUCCESS","provider":"STRATO_HIDRIVE","transport":"SFTP","files":1,"cloud_account_id":"private-account-id","target":"sftp://server/private"},
                [Path("test.txt")],
                {"name":"Cloud · Strato_sire25","kind":"CLOUD-SFTP","path":"/users/sire25/private","cloud_account_id":"private-account-id"},
            )
            txt = (Path(td)/"reports"/"job-2.txt").read_text(encoding="utf-8")
            raw = (Path(td)/"reports"/"job-2.json").read_text(encoding="utf-8")
            self.assertIn("Quelle → Ziel:", txt)
            self.assertIn("STRATO HiDrive", txt)
            self.assertNotIn("private-account-id", raw)
            self.assertNotIn("sftp://server/private", raw)
            self.assertNotIn("/users/sire25/private", raw)
            self.assertEqual(r["job_id"], "job-2")

    def test_local_report_can_be_reloaded_and_selected_as_latest(self):
        with tempfile.TemporaryDirectory() as td:
            store = DummyStore(td)
            persist_local_job_report(store, {"job_id":"job-a","status":"SUCCESS"}, [Path("a.txt")], {"name":"USB A","kind":"ORDNER"})
            persist_local_job_report(store, {"job_id":"job-b","status":"SUCCESS"}, [Path("b.txt")], {"name":"USB B","kind":"ORDNER"})
            self.assertEqual(load_local_job_report(store, "job-b")["target_label"], "USB B")
            self.assertEqual(len(list_local_job_reports(store)), 2)
            self.assertEqual(latest_local_job_report(store)["job_id"], "job-b")

    def test_filesystem_target_is_not_mislabeled_as_b2(self):
        info = target_summary({"name":"NAS Sicherung","kind":"NAS"},{"payload_target":"FILESYSTEM"})
        self.assertEqual(info["backend_label"], "NAS")
        self.assertEqual(info["target_label"], "NAS Sicherung")

    def test_report_lines_keep_one_job_identity(self):
        r = enrich_result({"job_id":"same-job","status":"SUCCESS","files":2}, [Path("a.txt"),Path("b.txt")], {"name":"USB","kind":"ORDNER"})
        text = "\n".join(report_lines(r))
        self.assertIn("Job-ID: same-job", text)
        self.assertIn("Quelle: a.txt, b.txt", text)
        self.assertIn("Ziel: USB", text)

    def test_history_tuple_keeps_filesystem_filter_and_exact_route(self):
        r = enrich_result(
            {"job_id":"history-job","status":"SUCCESS","provider":"STRATO_HIDRIVE","transport":"SFTP","files":1,"original_bytes":100,"stored_bytes":120},
            [Path("source.xlsx")],
            {"name":"Cloud · Strato_sire25","kind":"CLOUD-SFTP"},
        )
        row = _local_as_history_tuple(r)
        self.assertEqual(row[0], "history-job")
        self.assertEqual(row[15], "FILESYSTEM")
        self.assertIn("source.xlsx", row[8])
        self.assertIn("Strato_sire25", row[8])


if __name__ == "__main__":
    unittest.main()
