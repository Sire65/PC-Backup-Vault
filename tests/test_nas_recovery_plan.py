import unittest

from nas_recovery.recovery_plan import RecoveryPlanState, RecoveryStage


class RecoveryPlanTests(unittest.TestCase):
    def test_fresh_plan_only_allows_detection(self):
        state = RecoveryPlanState()
        self.assertTrue(state.allowed(RecoveryStage.DETECT))
        for stage in list(RecoveryStage)[1:]:
            self.assertFalse(state.allowed(stage))

    def test_progression_requires_verified_image(self):
        state = RecoveryPlanState(source_identified=True, source_assessed=True, image_path="C:/images/disk.img", image_complete=True)
        self.assertTrue(state.allowed(RecoveryStage.VERIFY))
        self.assertFalse(state.allowed(RecoveryStage.ANALYZE))
        verified = RecoveryPlanState(source_identified=True, source_assessed=True, image_path="C:/images/disk.img", image_complete=True, image_verified=True)
        self.assertTrue(verified.allowed(RecoveryStage.ANALYZE))

    def test_recovery_requires_analysis_and_separate_target(self):
        state = RecoveryPlanState(source_identified=True, source_assessed=True, image_path="C:/images/disk.img", image_complete=True, image_verified=True, analysis_complete=True)
        self.assertFalse(state.allowed(RecoveryStage.RECOVER))
        ready = RecoveryPlanState(**{**state.__dict__, "recovery_target": "D:/Recovered"})
        self.assertTrue(ready.allowed(RecoveryStage.RECOVER))

    def test_next_stage_is_deterministic(self):
        self.assertEqual(RecoveryPlanState().next_stage, RecoveryStage.DETECT)
        self.assertEqual(RecoveryPlanState(source_identified=True).next_stage, RecoveryStage.ASSESS)


if __name__ == "__main__":
    unittest.main()
