import unittest
from datetime import datetime, timedelta

from kc_backup_scheduler_observability import format_scheduler_details, scheduler_indicator
from kc_backup_scheduler_runtime import SchedulerRuntimeSummary


class SchedulerObservabilityTests(unittest.TestCase):
    def test_indicator_distinguishes_running_paused_and_stale(self):
        now = datetime(2026, 8, 29, 19, 35)
        running = SchedulerRuntimeSummary(last_tick_at="2026-08-29T19:34:00")
        self.assertEqual(scheduler_indicator(running, now=now)[0], "LÄUFT")

        paused = SchedulerRuntimeSummary(
            last_tick_at="2026-08-29T19:34:00",
            paused_reason="Backup läuft",
        )
        self.assertEqual(scheduler_indicator(paused, now=now)[0], "PAUSIERT")

        stale = SchedulerRuntimeSummary(last_tick_at="2026-08-29T19:20:00")
        self.assertEqual(scheduler_indicator(stale, now=now)[0], "FEHLER")

    def test_details_show_blocked_and_catchup_policy(self):
        summary = SchedulerRuntimeSummary(
            last_tick_at="2026-08-29T19:34:00",
            due_count=1,
            last_blocked_at="2026-08-29T19:30:00",
            last_blocked_program="kc-dp2",
            last_blocked_message="Quelle fehlt",
        )
        text = format_scheduler_details(summary, now=datetime(2026, 8, 29, 19, 35))
        self.assertIn("BLOCKED", text)
        self.assertIn("kc-dp2", text)
        self.assertIn("Quelle fehlt", text)
        self.assertIn("6 Stunden", text)
        self.assertIn("niemals unbeaufsichtigt", text)


if __name__ == "__main__":
    unittest.main()
