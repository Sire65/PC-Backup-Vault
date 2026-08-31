import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import control_center
from nas_recovery.control_center_ready_integration import enable_nas_ready_in_control_center
from nas_recovery.engine_handoff import build_engine_handoffs
from nas_recovery.recovery_engines import RecoveryEngine
from nas_recovery.recovery_coordinator import RecoveryCoordinator
from nas_recovery.recovery_session import RecoverySession
from nas_recovery.raid_virtual_plan import build_virtual_raid_plan


class RecoverySprintBundleTests(unittest.TestCase):
    def test_coordinator_requires_image_first_flow_and_distinct_devices(self):
        with tempfile.TemporaryDirectory() as td:
            image = Path(td) / "disk.img"
            image.write_bytes(b"\0" * (1024 * 1024 + 4096))
            target = Path(td) / "recovered"
            c = RecoveryCoordinator()
            c.identify_source("Disk 3", r"\\.\PhysicalDrive3", image.stat().st_size, device_id="disk-3")
            c.mark_source_assessed()
            c.attach_completed_image(image, device_id="disk-8")
            self.assertFalse(c.ready_for_recovery_tool)
            c.verify_attached_image()
            c.analyze_verified_image()
            c.select_recovery_target(target, device_id="disk-9")
            self.assertTrue(c.ready_for_recovery_tool)

    def test_virtual_raid_rejects_physical_drive(self):
        with self.assertRaises(ValueError):
            build_virtual_raid_plan([r"\\.\PhysicalDrive0", "member2.img"], "RAID1")

    def test_virtual_raid_plan_uses_images_only(self):
        with tempfile.TemporaryDirectory() as td:
            a = Path(td) / "a.img"; b = Path(td) / "b.img"
            a.write_bytes(b"a" * 4096); b.write_bytes(b"b" * 4096)
            plan = build_virtual_raid_plan([a, b], "RAID1")
            self.assertTrue(plan.ready_for_external_analysis)
            self.assertEqual(plan.member_count, 2)

    @patch("nas_recovery.engine_handoff.detect_recovery_engines")
    def test_engine_handoff_requires_full_gate(self, detect):
        detect.return_value = (RecoveryEngine("DMDE", True, r"C:\DMDE\dmde.exe", "test"),)
        with tempfile.TemporaryDirectory() as td:
            image = Path(td) / "disk.img"; image.write_bytes(b"x")
            target = Path(td) / "out"; target.mkdir()
            session = RecoverySession(
                image_path=str(image), image_complete=True, image_verified=True, analysis_complete=True,
                recovery_target=str(target), source_device_id="disk-3", image_device_id="disk-8",
                recovery_target_device_id="disk-9",
            )
            handoff = build_engine_handoffs(session)[0]
            self.assertTrue(handoff.ready)

    def test_leitstand_integration_promotes_nas_opener(self):
        enable_nas_ready_in_control_center(control_center)
        nas = next(m for m in control_center.MODULES if m.module_id == "nas")
        self.assertEqual(nas.opener_name, "open_nas_recovery")
        self.assertEqual(nas.readiness, "ready")


if __name__ == "__main__":
    unittest.main()
