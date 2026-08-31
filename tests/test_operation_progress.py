import unittest

from operation_progress import OperationProgressTracker, format_bytes, format_duration, progress_text


class OperationProgressTests(unittest.TestCase):
    def test_progress_calculates_percent_rate_and_eta(self):
        tracker = OperationProgressTracker(started_at=100.0)
        snap = tracker.snapshot(500, 1000, now=110.0, current_step="Prüfen")
        self.assertAlmostEqual(snap.percent, 50.0)
        self.assertAlmostEqual(snap.rate_per_second, 50.0)
        self.assertAlmostEqual(snap.eta_seconds, 10.0)
        self.assertEqual(snap.current_step, "Prüfen")

    def test_progress_finishes_at_100_and_zero_eta(self):
        tracker = OperationProgressTracker(started_at=10.0)
        snap = tracker.snapshot(2000, 1000, now=20.0)
        self.assertEqual(snap.done, 1000)
        self.assertEqual(snap.percent, 100.0)
        self.assertEqual(snap.eta_seconds, 0.0)
        self.assertTrue(snap.finished)

    def test_unknown_total_fails_closed_without_fake_percent(self):
        tracker = OperationProgressTracker(started_at=10.0)
        snap = tracker.snapshot(500, 0, now=20.0)
        self.assertEqual(snap.percent, 0.0)
        self.assertIsNone(snap.eta_seconds)
        self.assertFalse(snap.finished)

    def test_user_text_contains_amount_runtime_eta_and_step(self):
        tracker = OperationProgressTracker(started_at=0.0)
        snap = tracker.snapshot(1024, 2048, now=2.0, items_done=5, items_total=10, current_step="Kopieren")
        text = progress_text(snap)
        self.assertIn("50.0 %", text)
        self.assertIn("1.0 KB / 2.0 KB", text)
        self.assertIn("5 / 10 Dateien", text)
        self.assertIn("Laufzeit", text)
        self.assertIn("Restzeit", text)
        self.assertIn("Kopieren", text)

    def test_format_helpers_are_compact(self):
        self.assertEqual(format_bytes(0), "0 B")
        self.assertEqual(format_bytes(1024), "1.0 KB")
        self.assertEqual(format_duration(65), "1:05 min")
        self.assertEqual(format_duration(None), "–")


if __name__ == "__main__":
    unittest.main()
