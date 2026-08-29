import unittest
from datetime import date, time

from kc_backup_scheduler import BackupScheduleJob, ScheduleAction, ScheduleFrequency
from kc_backup_scheduler_ui import SchedulerModel


class SchedulerModelTests(unittest.TestCase):
    def test_model_add_pause_remove_and_month_calendar(self):
        job = BackupScheduleJob(
            program_id="kc-verwaltung",
            start_date=date(2026, 8, 29),
            start_time=time(2, 0),
            frequency=ScheduleFrequency.DAILY,
            action=ScheduleAction.BACKUP,
        )
        model = SchedulerModel()
        model.add(job)
        self.assertEqual(len(model.calendar_entries(2026, 8)), 3)

        model.set_enabled(job.job_id, False)
        self.assertEqual(model.calendar_entries(2026, 8), [])

        model.set_enabled(job.job_id, True)
        model.remove(job.job_id)
        self.assertEqual(model.jobs, [])

    def test_missing_job_cannot_be_silently_toggled(self):
        model = SchedulerModel()
        with self.assertRaises(KeyError):
            model.set_enabled("missing", False)


if __name__ == "__main__":
    unittest.main()
