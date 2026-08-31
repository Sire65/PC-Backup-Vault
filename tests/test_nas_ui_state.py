import unittest

from nas_recovery.ui_state import NasUiState


class NasUiStateTests(unittest.TestCase):
    def test_no_disk_disables_disk_actions_and_image(self):
        state = NasUiState(busy=False, disk_selected=False, image_active=False)
        self.assertTrue(state.can_scan)
        self.assertFalse(state.can_use_disk_actions)
        self.assertFalse(state.can_start_image)
        self.assertFalse(state.can_cancel_image)
        self.assertTrue(state.can_open_secondary_tools)

    def test_selected_disk_enables_safe_actions(self):
        state = NasUiState(busy=False, disk_selected=True, image_active=False)
        self.assertTrue(state.can_use_disk_actions)
        self.assertTrue(state.can_start_image)
        self.assertTrue(state.can_open_secondary_tools)

    def test_busy_operation_disables_competing_actions(self):
        state = NasUiState(busy=True, disk_selected=True, image_active=False)
        self.assertFalse(state.can_scan)
        self.assertFalse(state.can_use_disk_actions)
        self.assertFalse(state.can_start_image)
        self.assertFalse(state.can_open_secondary_tools)
        self.assertFalse(state.can_cancel_image)

    def test_cancel_only_enabled_for_active_image(self):
        image = NasUiState(busy=True, disk_selected=True, image_active=True)
        smart = NasUiState(busy=True, disk_selected=True, image_active=False)
        self.assertTrue(image.can_cancel_image)
        self.assertFalse(smart.can_cancel_image)


if __name__ == "__main__":
    unittest.main()
