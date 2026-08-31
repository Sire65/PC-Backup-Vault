import unittest

from framework_core_adapters import FRAMEWORK_PROVENANCE, framework_studio_version_resolved
from function_catalog import visible_tasks
from operation_progress import OperationProgressTracker, progress_text
from release_gate import evaluate_release_gate
from user_guidance import friendly_error, guidance_for_task


class ReleaseUsabilityBundleTests(unittest.TestCase):
    def test_simple_mode_has_six_clear_primary_tasks(self):
        tasks = visible_tasks(advanced=False)
        self.assertEqual(len(tasks), 6)
        self.assertEqual({t.task_id for t in tasks}, {"secure", "check_disk", "recover", "restore", "projects", "system"})

    def test_every_primary_task_has_plain_language_guidance(self):
        for task in visible_tasks(advanced=False):
            guidance = guidance_for_task(task.task_id)
            self.assertTrue(guidance.title)
            self.assertTrue(guidance.message)
            self.assertTrue(guidance.action)

    def test_friendly_error_hides_raw_auth_wording(self):
        msg = friendly_error(RuntimeError("auth password failed"))
        self.assertIn("Anmeldung", msg)
        self.assertNotIn("auth password failed", msg)

    def test_long_operations_report_percent_amount_runtime_eta_and_step(self):
        tracker = OperationProgressTracker(started_at=100.0)
        snap = tracker.snapshot(512, 1024, now=110.0, items_done=5, items_total=10, current_step="Prüfen")
        text = progress_text(snap)
        self.assertAlmostEqual(snap.percent, 50.0)
        self.assertAlmostEqual(snap.eta_seconds, 10.0)
        self.assertIn("50.0 %", text)
        self.assertIn("5 / 10 Dateien", text)
        self.assertIn("Laufzeit", text)
        self.assertIn("Restzeit", text)
        self.assertIn("Prüfen", text)

    def test_unknown_total_never_invents_progress_or_eta(self):
        tracker = OperationProgressTracker(started_at=100.0)
        snap = tracker.snapshot(512, 0, now=110.0)
        self.assertEqual(snap.percent, 0.0)
        self.assertIsNone(snap.eta_seconds)

    def test_framework_studio_baseline_is_unambiguous_but_stays_candidate(self):
        self.assertTrue(framework_studio_version_resolved())
        self.assertEqual(FRAMEWORK_PROVENANCE["studio_version"], "1.38.39")
        self.assertEqual(FRAMEWORK_PROVENANCE["baseline_path"], "BASELINE_V1_38_39")
        self.assertEqual(FRAMEWORK_PROVENANCE["candidate_status"], "YELLOW")

    def test_release_gate_fails_closed_until_all_prerequisites_green(self):
        blocked = evaluate_release_gate(
            ci_green=True,
            required_modules={"backup": True, "nas": True, "restore": True},
            framework_version_resolved=False,
            main_untouched=True,
        )
        self.assertFalse(blocked.ready)
        self.assertEqual(blocked.status, "blocked")

    def test_release_gate_can_only_create_candidate_not_merge(self):
        ready = evaluate_release_gate(
            ci_green=True,
            required_modules={"backup": True, "nas": True, "restore": True},
            framework_version_resolved=framework_studio_version_resolved(),
            main_untouched=True,
        )
        self.assertTrue(ready.ready)
        self.assertEqual(ready.status, "candidate")


if __name__ == "__main__":
    unittest.main()