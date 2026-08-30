import json
import tempfile
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path

from kc_backup_scheduler import BackupScheduleJob, ScheduleAction, ScheduleFrequency
from kc_backup_scheduler_runtime import (
    claim_dispatch,
    due_dispatches,
    mark_dispatch,
    occurrence_state,
    prune_runtime,
    record_scheduler_tick,
    runtime_summary,
)


class SchedulerRuntimeTests(unittest.TestCase):
    def test_due_backup_is_found_inside_catchup_window(self):
        job = BackupScheduleJob(
            program_id="kc-dp2",
            start_date=date(2026, 8, 29),
            start_time=time(18, 0),
            frequency=ScheduleFrequency.DAILY,
            action=ScheduleAction.BACKUP,
        )
        due = due_dispatches([job], now=datetime(2026, 8, 29, 19, 0), catchup=timedelta(hours=2))
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0].program_id, "kc-dp2")
        self.assertEqual(due[0].scheduled_at, datetime(2026, 8, 29, 18, 0))

    def test_old_missed_job_is_not_started_late(self):
        job = BackupScheduleJob(
            program_id="kc-dp2",
            start_date=date(2026, 8, 29),
            start_time=time(2, 0),
            frequency=ScheduleFrequency.DAILY,
            action=ScheduleAction.BACKUP,
        )
        due = due_dispatches([job], now=datetime(2026, 8, 29, 19, 0), catchup=timedelta(hours=6))
        self.assertEqual(due, [])

    def test_restore_test_is_never_unattended_dispatch(self):
        job = BackupScheduleJob(
            program_id="kc-verwaltung",
            start_date=date(2026, 8, 29),
            start_time=time(19, 0),
            frequency=ScheduleFrequency.DAILY,
            action=ScheduleAction.RESTORE_TEST,
        )
        self.assertEqual(due_dispatches([job], now=datetime(2026, 8, 29, 19, 1)), [])

    def test_live_lease_blocks_duplicate_and_success_is_final(self):
        job = BackupScheduleJob(
            program_id="kc-marktkasse",
            start_date=date(2026, 8, 29),
            start_time=time(19, 0),
            frequency=ScheduleFrequency.DAILY,
            action=ScheduleAction.BACKUP,
        )
        dispatch = due_dispatches([job], now=datetime(2026, 8, 29, 19, 5))[0]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "runtime.json"
            now = datetime(2026, 8, 29, 19, 5)
            self.assertTrue(claim_dispatch(path, dispatch, now=now))
            self.assertFalse(claim_dispatch(path, dispatch, now=now + timedelta(minutes=30)))
            mark_dispatch(path, dispatch, state="SUCCESS", now=now + timedelta(minutes=40))
            self.assertEqual(occurrence_state(path, dispatch), "SUCCESS")
            self.assertFalse(claim_dispatch(path, dispatch, now=now + timedelta(hours=3)))

    def test_failed_occurrence_is_final_and_does_not_retry_every_minute(self):
        job = BackupScheduleJob(
            program_id="kc-dp2",
            start_date=date(2026, 8, 29),
            start_time=time(19, 0),
            frequency=ScheduleFrequency.DAILY,
            action=ScheduleAction.BACKUP,
        )
        dispatch = due_dispatches([job], now=datetime(2026, 8, 29, 19, 5))[0]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "runtime.json"
            now = datetime(2026, 8, 29, 19, 5)
            self.assertTrue(claim_dispatch(path, dispatch, now=now))
            mark_dispatch(path, dispatch, state="FAILED", now=now + timedelta(minutes=1), message="Testfehler")
            self.assertFalse(claim_dispatch(path, dispatch, now=now + timedelta(minutes=2)))
            self.assertFalse(claim_dispatch(path, dispatch, now=now + timedelta(hours=3)))

    def test_stale_claim_can_be_recovered_after_lease(self):
        job = BackupScheduleJob(
            program_id="kc-dp2",
            start_date=date(2026, 8, 29),
            start_time=time(19, 0),
            frequency=ScheduleFrequency.DAILY,
            action=ScheduleAction.VERIFY,
        )
        dispatch = due_dispatches([job], now=datetime(2026, 8, 29, 19, 5))[0]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "runtime.json"
            first = datetime(2026, 8, 29, 19, 5)
            self.assertTrue(claim_dispatch(path, dispatch, now=first, lease=timedelta(hours=1)))
            self.assertTrue(claim_dispatch(path, dispatch, now=first + timedelta(hours=2), lease=timedelta(hours=1)))

    def test_disabled_job_is_not_due(self):
        job = BackupScheduleJob(
            program_id="kc-dp2",
            start_date=date(2026, 8, 29),
            start_time=time(19, 0),
            frequency=ScheduleFrequency.DAILY,
            action=ScheduleAction.BACKUP,
            enabled=False,
        )
        self.assertEqual(due_dispatches([job], now=datetime(2026, 8, 29, 19, 5)), [])

    def test_heartbeat_and_summary_are_read_only_observability(self):
        job = BackupScheduleJob(
            program_id="kc-dp2",
            start_date=date(2026, 8, 29),
            start_time=time(19, 0),
            frequency=ScheduleFrequency.DAILY,
            action=ScheduleAction.BACKUP,
        )
        dispatch = due_dispatches([job], now=datetime(2026, 8, 29, 19, 5))[0]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "runtime.json"
            tick = datetime(2026, 8, 29, 19, 5)
            record_scheduler_tick(path, now=tick, paused_reason="Backup läuft", due_count=2)
            self.assertTrue(claim_dispatch(path, dispatch, now=tick))
            mark_dispatch(path, dispatch, state="BLOCKED", now=tick + timedelta(minutes=1), message="Quelle fehlt")
            summary = runtime_summary(path)
            self.assertEqual(summary.last_tick_at, "2026-08-29T19:05:00")
            self.assertEqual(summary.paused_reason, "Backup läuft")
            self.assertEqual(summary.due_count, 2)
            self.assertEqual(summary.last_blocked_program, "kc-dp2")
            self.assertEqual(summary.last_blocked_message, "Quelle fehlt")
            self.assertEqual(occurrence_state(path, dispatch), "BLOCKED")

    def test_prune_removes_only_old_terminal_occurrences(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "runtime.json"
            raw = {
                "store_version": 1,
                "meta": {},
                "occurrences": {
                    "old-success": {"state": "SUCCESS", "finished_at": "2026-01-01T00:00:00"},
                    "old-failed": {"state": "FAILED", "finished_at": "2026-01-02T00:00:00"},
                    "old-running": {"state": "RUNNING", "claimed_at": "2026-01-01T00:00:00"},
                    "recent-success": {"state": "SUCCESS", "finished_at": "2026-08-20T00:00:00"},
                },
            }
            path.write_text(json.dumps(raw), encoding="utf-8")
            removed = prune_runtime(path, now=datetime(2026, 8, 29), retention=timedelta(days=90))
            self.assertEqual(removed, 2)
            saved = json.loads(path.read_text(encoding="utf-8"))["occurrences"]
            self.assertIn("old-running", saved)
            self.assertIn("recent-success", saved)
            self.assertNotIn("old-success", saved)
            self.assertNotIn("old-failed", saved)


if __name__ == "__main__":
    unittest.main()
