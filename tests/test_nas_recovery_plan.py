import unittest
from dataclasses import replace

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
        verified = replace(state, image_verified=True)
        self.assertTrue(verified.allowed(RecoveryStage.ANALYZE))

    def test_recovery_requires_known_distinct_physical_devices(self):
        state = RecoveryPlanState(
            source_identified=True,
            source_assessed=True,
            image_path="C:/images/disk.img",
            image_complete=True,
            image_verified=True,
            analysis_complete=True,
            recovery_target="D:/Recovered",
        )
        self.assertFalse(state.allowed(RecoveryStage.RECOVER))
        ready = replace(
            state,
            source_device_id="disk-3",
            image_device_id="disk-8",
            recovery_target_device_id="disk-9",
        )
        self.assertTrue(ready.allowed(RecoveryStage.RECOVER))
        self.assertFalse(replace(ready, recovery_target_device_id="disk-8").allowed(RecoveryStage.RECOVER))
        self.assertFalse(replace(ready, recovery_target_device_id="disk-3").allowed(RecoveryStage.RECOVER))

    def test_next_stage_is_deterministic(self):
        self.assertEqual(RecoveryPlanState().next_stage, RecoveryStage.DETECT)
        self.assertEqual(RecoveryPlanState(source_identified=True).next_stage, RecoveryStage.ASSESS)


if __name__ == "__main__":
    unittest.main()
