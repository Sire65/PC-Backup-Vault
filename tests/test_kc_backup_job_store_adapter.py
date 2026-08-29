import tempfile
import unittest
from datetime import date, time
from pathlib import Path

from kc_backup_engine_adapter import (
    execute_prepared_backup,
    prepare_backup_execution,
    prepare_one_touch_backup,
)
from kc_backup_job_store import load_jobs, save_jobs
from kc_backup_scheduler import BackupScheduleJob, ScheduleAction, ScheduleFrequency


class BackupJobStoreAndAdapterTests(unittest.TestCase):
    def test_jobs_roundtrip_persists_action_and_pause_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scheduler.json"
            original = BackupScheduleJob(
                program_id="kc-verwaltung",
                action=ScheduleAction.VERIFY,
                start_date=date(2026, 8, 30),
                start_time=time(3, 15),
                frequency=ScheduleFrequency.WEEKLY,
                weekday=6,
                enabled=False,
                display_name="Vollprüfung",
            )
            save_jobs(path, [original])
            loaded = load_jobs(path)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].job_id, original.job_id)
            self.assertEqual(loaded[0].action, ScheduleAction.VERIFY)
            self.assertFalse(loaded[0].enabled)
            self.assertEqual(loaded[0].start_time, time(3, 15))

    def test_store_write_is_valid_json_and_missing_file_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scheduler.json"
            self.assertEqual(load_jobs(path), [])
            save_jobs(path, [])
            self.assertIn('"store_version": 1', path.read_text(encoding="utf-8"))

    def test_one_touch_preflight_blocks_missing_recovery_material(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "data.txt"
            source.write_text("safe", encoding="utf-8")
            prepared = prepare_one_touch_backup(
                program_id="kc-verwaltung",
                paths=[source],
                target_ready=True,
                recovery_material_ready=False,
            )
            self.assertFalse(prepared.allowed)
            self.assertTrue(any("Recovery" in item for item in prepared.blockers))

    def test_non_backup_action_cannot_use_backup_engine_adapter(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "data.txt"
            source.write_text("safe", encoding="utf-8")
            prepared = prepare_backup_execution(
                program_id="dp2",
                action=ScheduleAction.RESTORE_TEST,
                paths=[source],
                target_ready=True,
                recovery_material_ready=True,
            )
            self.assertFalse(prepared.allowed)
            self.assertIn("RESTORE_TEST", prepared.blockers[0])

    def test_allowed_prepared_backup_calls_existing_engine_signature(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "data.txt"
            source.write_text("safe", encoding="utf-8")
            prepared = prepare_one_touch_backup(
                program_id="pc-manager",
                paths=[source],
                target_ready=True,
                recovery_material_ready=True,
                backup_mode="FULL",
                payload_target="B2",
            )
            calls = []

            def fake_engine(*args, **kwargs):
                calls.append((args, kwargs))
                return "job-123"

            result = execute_prepared_backup(
                prepared,
                engine=fake_engine,
                dsn="dsn",
                key_b64="key",
                profile={"soft_limit_mb": 350},
                config={"retention_days": 90},
            )
            self.assertEqual(result, "job-123")
            self.assertEqual(len(calls), 1)
            args, kwargs = calls[0]
            self.assertEqual(args[0], "dsn")
            self.assertEqual(kwargs["trigger_type"], "ONE_TOUCH")
            self.assertEqual(kwargs["backup_mode"], "FULL")
            self.assertEqual(kwargs["payload_target"], "B2")

    def test_blocked_prepared_backup_never_calls_engine(self):
        with tempfile.TemporaryDirectory() as tmp:
            prepared = prepare_one_touch_backup(
                program_id="pc-manager",
                paths=[Path(tmp) / "missing.txt"],
                target_ready=True,
                recovery_material_ready=True,
            )
            called = False

            def fake_engine(*args, **kwargs):
                nonlocal called
                called = True

            with self.assertRaises(RuntimeError):
                execute_prepared_backup(
                    prepared,
                    engine=fake_engine,
                    dsn="dsn",
                    key_b64="key",
                    profile={},
                    config={},
                )
            self.assertFalse(called)


if __name__ == "__main__":
    unittest.main()
