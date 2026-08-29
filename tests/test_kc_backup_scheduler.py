import unittest
from datetime import date, time

from kc_backup_scheduler import (
    BackupExperience,
    BackupScheduleJob,
    OneTouchBackupPlan,
    SAFE_DEFAULT_PROFILE,
    ScheduleFrequency,
    build_calendar,
)


class BackupSchedulerTests(unittest.TestCase):
    def test_one_touch_plan_keeps_professional_safety_chain(self):
        plan = OneTouchBackupPlan(program_id="kc-verwaltung")
        self.assertEqual(plan.visible_summary(), "Jetzt sicher sichern")
        self.assertEqual(
            plan.execution_job_types(),
            ("PREFLIGHT", "BACKUP", "VERIFY", "RESTORE_POINT", "AUDIT"),
        )
        self.assertEqual(plan.profile.security_level, "MAXIMUM")
        self.assertTrue(plan.profile.protect_last_known_good)
        self.assertFalse(plan.profile.allow_silent_restore)

    def test_experience_levels_are_explicit(self):
        self.assertEqual(
            {item.value for item in BackupExperience},
            {"SIMPLE", "ADVANCED", "EXPERT"},
        )

    def test_daily_job_builds_calendar_entries(self):
        job = BackupScheduleJob(
            program_id="kc-verwaltung",
            start_date=date(2026, 8, 29),
            start_time=time(2, 0),
            frequency=ScheduleFrequency.DAILY,
        )
        entries = build_calendar([job], date(2026, 8, 29), date(2026, 8, 31))
        self.assertEqual(len(entries), 3)
        self.assertEqual(entries[0].starts_at.hour, 2)
        self.assertEqual(entries[-1].starts_at.date(), date(2026, 8, 31))

    def test_weekly_job_uses_requested_weekday(self):
        job = BackupScheduleJob(
            program_id="dp2",
            start_date=date(2026, 8, 29),
            start_time=time(3, 0),
            frequency=ScheduleFrequency.WEEKLY,
            weekday=6,
        )
        entries = build_calendar([job], date(2026, 8, 29), date(2026, 9, 13))
        self.assertEqual([entry.starts_at.date() for entry in entries], [date(2026, 8, 30), date(2026, 9, 6), date(2026, 9, 13)])

    def test_monthly_job_skips_months_without_requested_day(self):
        job = BackupScheduleJob(
            program_id="kc-futura",
            start_date=date(2026, 8, 31),
            start_time=time(4, 0),
            frequency=ScheduleFrequency.MONTHLY,
            day_of_month=31,
        )
        entries = build_calendar([job], date(2026, 8, 31), date(2026, 11, 30))
        self.assertEqual([entry.starts_at.date() for entry in entries], [date(2026, 8, 31), date(2026, 10, 31)])

    def test_disabled_job_never_appears_in_calendar(self):
        job = BackupScheduleJob(
            program_id="pc-manager",
            start_date=date(2026, 8, 29),
            start_time=time(2, 0),
            enabled=False,
        )
        self.assertEqual(build_calendar([job], date(2026, 8, 29), date(2026, 9, 2)), [])

    def test_default_profile_requires_recovery_and_restore_test(self):
        self.assertTrue(SAFE_DEFAULT_PROFILE.require_recovery_material)
        self.assertTrue(SAFE_DEFAULT_PROFILE.restore_test)
        self.assertTrue(SAFE_DEFAULT_PROFILE.full_verify)


if __name__ == "__main__":
    unittest.main()
