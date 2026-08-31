import unittest

import control_center
import framework_core_adapters as fca


class ControlCenterArchitectureTests(unittest.TestCase):
    def test_required_modules_are_registered(self):
        ids = {m.module_id for m in control_center.MODULES}
        self.assertEqual(
            ids,
            {"backup", "cloud", "disk", "nas", "finder", "git", "restore", "tuev", "settings"},
        )

    def test_nas_is_not_pretended_ready(self):
        nas = next(m for m in control_center.MODULES if m.module_id == "nas")
        self.assertEqual(nas.readiness, "integration")
        self.assertIsNone(nas.opener_name)

    def test_framework_provenance_is_explicit(self):
        self.assertIn("window_core", fca.FRAMEWORK_PROVENANCE)
        self.assertIn("table_core", fca.FRAMEWORK_PROVENANCE)
        self.assertIn("design_core", fca.FRAMEWORK_PROVENANCE)
        self.assertIn("navigation_core", fca.FRAMEWORK_PROVENANCE)

    def test_status_palette_covers_four_state_semantics(self):
        self.assertNotEqual(fca.status_color("ok"), fca.status_color("warn"))
        self.assertNotEqual(fca.status_color("warn"), fca.status_color("error"))
        self.assertNotEqual(fca.status_color("error"), fca.status_color("off"))


if __name__ == "__main__":
    unittest.main()
