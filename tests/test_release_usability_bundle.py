import unittest

from function_catalog import visible_tasks
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
            framework_version_resolved=True,
            main_untouched=True,
        )
        self.assertTrue(ready.ready)
        self.assertEqual(ready.status, "candidate")


if __name__ == "__main__":
    unittest.main()
