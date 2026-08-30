import json
import tempfile
import unittest
from datetime import date, time
from pathlib import Path

from kc_backup_job_store import load_jobs, load_jobs_resilient
from kc_backup_scheduler_control import SchedulerControl, load_scheduler_control, save_scheduler_control
from kc_backup_scheduler_program_guard import registered_program_ids


class SchedulerSafetyTests(unittest.TestCase):
    def test_master_control_defaults_off(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "control.json"
            self.assertFalse(load_scheduler_control(path).enabled)
            save_scheduler_control(path, SchedulerControl(enabled=True))
            self.assertTrue(load_scheduler_control(path).enabled)

    def test_unknown_control_version_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "control.json"
            path.write_text('{"store_version":99,"enabled":true}', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_scheduler_control(path)

    def test_resilient_loader_keeps_valid_job_and_skips_bad_sibling(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.json"
            raw = {
                "store_version": 1,
                "jobs": [
                    {
                        "job_id": "good",
                        "program_id": "kc-dp2",
                        "action": "BACKUP",
                        "display_name": "Gut",
                        "start_date": date(2026, 8, 29).isoformat(),
                        "start_time": time(2, 0).strftime("%H:%M:%S"),
                        "frequency": "DAILY",
                        "enabled": True,
                        "weekday": None,
                        "day_of_month": None,
                        "profile": {"name": "KC MAXIMUM"},
                    },
                    {
                        "job_id": "bad",
                        "program_id": "kc-dp2",
                        "action": "NICHT_GUELTIG",
                        "start_date": "2026-08-29",
                        "start_time": "02:00:00",
                    },
                ],
            }
            path.write_text(json.dumps(raw), encoding="utf-8")
            result = load_jobs_resilient(path)
            self.assertEqual([job.job_id for job in result.jobs], ["good"])
            self.assertEqual(len(result.warnings), 1)
            with self.assertRaises(ValueError):
                load_jobs(path)

    def test_unknown_job_store_version_is_hard_failure_even_resilient(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "jobs.json"
            path.write_text('{"store_version":99,"jobs":[]}', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_jobs_resilient(path)

    def test_program_guard_contains_only_registered_ids(self):
        ids = registered_program_ids()
        self.assertIn("pc-backup-vault", ids)
        self.assertIn("kc-dp2", ids)
        self.assertIn("kc-marktkasse", ids)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertNotIn("kc-dp22", ids)


if __name__ == "__main__":
    unittest.main()
