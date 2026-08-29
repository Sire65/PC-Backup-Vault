import unittest
from datetime import date, time

from kc_backup_scheduler import BackupExperience, BackupScheduleJob, ScheduleAction, ScheduleFrequency
from kc_backup_scheduler_ui import (
    SchedulerModel,
    VIEW_DAY,
    VIEW_MONTH,
    VIEW_WEEK,
    experience_permissions,
    move_anchor,
    view_window,
)


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

    def test_day_week_month_windows(self):
        anchor = date(2026, 8, 29)  # Saturday
        self.assertEqual(view_window(anchor, VIEW_DAY), (anchor, anchor))
        self.assertEqual(view_window(anchor, VIEW_WEEK), (date(2026, 8, 24), date(2026, 8, 30)))
        self.assertEqual(view_window(anchor, VIEW_MONTH), (date(2026, 8, 1), date(2026, 8, 31)))

    def test_navigation_respects_view_granularity(self):
        anchor = date(2026, 8, 31)
        self.assertEqual(move_anchor(anchor, VIEW_DAY, 1), date(2026, 9, 1))
        self.assertEqual(move_anchor(anchor, VIEW_WEEK, 1), date(2026, 9, 7))
        self.assertEqual(move_anchor(anchor, VIEW_MONTH, 1), date(2026, 9, 30))

    def test_simple_advanced_expert_permissions(self):
        simple = experience_permissions(BackupExperience.SIMPLE)
        advanced = experience_permissions(BackupExperience.ADVANCED)
        expert = experience_permissions(BackupExperience.EXPERT)

        self.assertFalse(simple["edit_jobs"])
        self.assertFalse(simple["show_technical_details"])
        self.assertTrue(advanced["edit_jobs"])
        self.assertFalse(advanced["show_technical_details"])
        self.assertTrue(expert["edit_jobs"])
        self.assertTrue(expert["show_technical_details"])
        self.assertTrue(simple["maximum_security_locked"])
        self.assertTrue(advanced["maximum_security_locked"])
        self.assertTrue(expert["maximum_security_locked"])

    def test_unknown_view_fails_explicitly(self):
        with self.assertRaises(ValueError):
            view_window(date(2026, 8, 29), "Jahr")
        with self.assertRaises(ValueError):
            move_anchor(date(2026, 8, 29), "Jahr", 1)


if __name__ == "__main__":
    unittest.main()
