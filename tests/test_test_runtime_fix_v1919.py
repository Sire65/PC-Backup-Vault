import time
import unittest

from test_runtime_fix_v1919 import delivery_summary_v1919, run_with_deadline, timed_percent


class TestRuntimeFixV1919(unittest.TestCase):
    def test_timed_percent_never_claims_complete(self):
        self.assertEqual(timed_percent(0, 10), 0)
        self.assertGreater(timed_percent(5, 10), 0)
        self.assertEqual(timed_percent(100, 10), 95)

    def test_selected_channels_count_as_success(self):
        payload = {
            "ok": False,
            "partial": True,
            "results": [
                {
                    "partial": True,
                    "selectedChannels": ["push"],
                    "provider": "web-push",
                }
            ],
        }
        any_success, any_failure, summary = delivery_summary_v1919(payload)
        self.assertTrue(any_success)
        self.assertFalse(any_failure)
        self.assertIn("Push: OK", summary)
        self.assertIn("web-push", summary)

    def test_displayed_push_is_success(self):
        payload = {
            "results": [
                {
                    "channel": "push",
                    "status": "displayed",
                    "provider": "web-push",
                }
            ]
        }
        any_success, any_failure, summary = delivery_summary_v1919(payload)
        self.assertTrue(any_success)
        self.assertFalse(any_failure)
        self.assertIn("Push: OK", summary)

    def test_top_level_ok_without_details_is_not_error(self):
        any_success, any_failure, summary = delivery_summary_v1919({"ok": True})
        self.assertTrue(any_success)
        self.assertFalse(any_failure)
        self.assertEqual(summary, "Versand vom Server bestätigt")

    def test_real_failure_stays_failure(self):
        payload = {
            "ok": False,
            "failed": 1,
            "results": [
                {
                    "channel": "email",
                    "status": "failed",
                    "provider": "brevo",
                    "error": "provider rejected",
                }
            ],
        }
        any_success, any_failure, summary = delivery_summary_v1919(payload)
        self.assertFalse(any_success)
        self.assertTrue(any_failure)
        self.assertIn("E-Mail: FEHLER", summary)

    def test_deadline_returns_control(self):
        started = time.monotonic()
        done, value, error = run_with_deadline(lambda: time.sleep(0.25), 0.05)
        elapsed = time.monotonic() - started
        self.assertFalse(done)
        self.assertIsNone(value)
        self.assertIsInstance(error, TimeoutError)
        self.assertLess(elapsed, 0.20)

    def test_deadline_returns_result(self):
        done, value, error = run_with_deadline(lambda: (True, "OK"), 1)
        self.assertTrue(done)
        self.assertEqual(value, (True, "OK"))
        self.assertIsNone(error)


if __name__ == "__main__":
    unittest.main()
