import unittest

from final_consolidation import LONG_RUNNING_OPERATIONS, REQUIRED_FRAMEWORK_ADAPTERS, REQUIRED_PRIMARY_TASKS, evaluate_final_consolidation


class FinalConsolidationTests(unittest.TestCase):
    def _good_args(self):
        return dict(
            ci_green=True,
            regression_green=True,
            safety_green=True,
            studio_rules_green=True,
            framework_version_resolved=True,
            framework_adapters={name: True for name in REQUIRED_FRAMEWORK_ADAPTERS},
            progress_coverage={name: True for name in LONG_RUNNING_OPERATIONS},
            primary_tasks=REQUIRED_PRIMARY_TASKS,
            main_untouched=True,
        )

    def test_all_green_yields_ready_candidate_gate(self):
        result = evaluate_final_consolidation(**self._good_args())
        self.assertTrue(result.ready)
        self.assertEqual(result.findings, ())

    def test_framework_version_discrepancy_blocks_release(self):
        args = self._good_args(); args["framework_version_resolved"] = False
        result = evaluate_final_consolidation(**args)
        self.assertFalse(result.ready)
        self.assertIn("FRAMEWORK_VERSION", {f.code for f in result.findings})

    def test_any_missing_progress_coverage_blocks_release(self):
        args = self._good_args(); args["progress_coverage"]["project_finder"] = False
        result = evaluate_final_consolidation(**args)
        self.assertFalse(result.ready)
        self.assertIn("PROGRESS", {f.code for f in result.findings})

    def test_missing_framework_adapter_blocks_release(self):
        args = self._good_args(); args["framework_adapters"]["TableCore"] = False
        result = evaluate_final_consolidation(**args)
        self.assertFalse(result.ready)
        self.assertIn("FRAMEWORK_CORE", {f.code for f in result.findings})

    def test_changed_primary_task_contract_blocks_release(self):
        args = self._good_args(); args["primary_tasks"] = tuple(reversed(REQUIRED_PRIMARY_TASKS))
        result = evaluate_final_consolidation(**args)
        self.assertFalse(result.ready)
        self.assertIn("UX", {f.code for f in result.findings})


if __name__ == "__main__":
    unittest.main()
