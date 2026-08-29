import tempfile
import unittest
from datetime import date, datetime, time
from pathlib import Path

from kc_backup_program_status import (
    ProgramRuntimeStatus,
    load_program_statuses,
    next_job_for_program,
    record_program_failure,
    record_program_success,
    record_program_verify,
    traffic_light,
)
from kc_backup_scheduler import BackupScheduleJob, ScheduleFrequency


class KCProgramStatusTests(unittest.TestCase):
    def test_success_roundtrip_and_failure_preserves_last_good(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "status.json"
            stamp = datetime(2026, 8, 29, 12, 30)
            record_program_success(path, program_id="kc-dp2", job_id="job-1", verify_status="PASS", at=stamp)
            first = load_program_statuses(path)["kc-dp2"]
            self.assertEqual(first.last_job_id, "job-1")
            self.assertEqual(first.verify_status, "PASS")
            self.assertIsNone(first.last_error)

            record_program_failure(path, program_id="kc-dp2", error="Netzwerkfehler")
            failed = load_program_statuses(path)["kc-dp2"]
            self.assertEqual(failed.last_job_id, "job-1")
            self.assertEqual(failed.last_backup_at, first.last_backup_at)
            self.assertEqual(failed.verify_status, "PASS")
            self.assertEqual(failed.last_error, "Netzwerkfehler")

    def test_verify_update_does_not_change_last_backup_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "status.json"
            stamp = datetime(2026, 8, 29, 12, 30)
            record_program_success(path, program_id="kc-dp2", job_id="job-1", verify_status="PASS", at=stamp)
            before = load_program_statuses(path)["kc-dp2"]
            record_program_verify(path, program_id="kc-dp2", verify_status="FAIL", error="Hashfehler")
            after = load_program_statuses(path)["kc-dp2"]
            self.assertEqual(after.last_backup_at, before.last_backup_at)
            self.assertEqual(after.last_job_id, "job-1")
            self.assertEqual(after.verify_status, "FAIL")
            self.assertEqual(after.last_error, "Hashfehler")

    def test_next_job_uses_program_id_and_skips_disabled(self):
        jobs = [
            BackupScheduleJob(
                program_id="kc-dp2",
                start_date=date(2026, 8, 29),
                start_time=time(14, 0),
                frequency=ScheduleFrequency.DAILY,
            ),
            BackupScheduleJob(
                program_id="kc-dp2",
                start_date=date(2026, 8, 29),
                start_time=time(13, 0),
                frequency=ScheduleFrequency.DAILY,
                enabled=False,
            ),
            BackupScheduleJob(
                program_id="kc-verwaltung",
                start_date=date(2026, 8, 29),
                start_time=time(12, 0),
                frequency=ScheduleFrequency.DAILY,
            ),
        ]
        nxt = next_job_for_program(jobs, "kc-dp2", now=datetime(2026, 8, 29, 13, 30))
        self.assertEqual(nxt, datetime(2026, 8, 29, 14, 0))

    def test_traffic_light_is_fail_closed(self):
        self.assertEqual(traffic_light(scope_ready=False, runtime=None)[0], "ROT")
        self.assertEqual(traffic_light(scope_ready=True, runtime=None)[0], "GELB")
        good = ProgramRuntimeStatus("kc-dp2", "2026-08-29T12:00:00", "j1", "PASS", None)
        self.assertEqual(traffic_light(scope_ready=True, runtime=good)[0], "GRÜN")
        bad = ProgramRuntimeStatus("kc-dp2", "2026-08-29T12:00:00", "j1", "PASS", "Fehler")
        self.assertEqual(traffic_light(scope_ready=True, runtime=bad)[0], "ROT")

    def test_unknown_store_version_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "status.json"
            path.write_text('{"store_version":99,"programs":{}}', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_program_statuses(path)


if __name__ == "__main__":
    unittest.main()
