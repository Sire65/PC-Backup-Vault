import tempfile
import unittest
from pathlib import Path

from nas_recovery.image_verification import VerificationCancelled, manifest_matches_image, verify_image, write_manifest
from nas_recovery.recovery_coordinator import RecoveryCoordinator
from nas_recovery.recovery_session import RecoverySession


class ImageVerificationTests(unittest.TestCase):
    def test_verify_and_manifest(self):
        with tempfile.TemporaryDirectory() as td:
            image = Path(td) / "disk.img"
            image.write_bytes(b"abc" * 1000)
            result = verify_image(image)
            self.assertEqual(result.size, 3000)
            manifest = write_manifest(result)
            self.assertTrue(manifest_matches_image(manifest))

    def test_manifest_detects_changed_image(self):
        with tempfile.TemporaryDirectory() as td:
            image = Path(td) / "disk.img"
            image.write_bytes(b"safe")
            manifest = write_manifest(verify_image(image))
            image.write_bytes(b"changed")
            self.assertFalse(manifest_matches_image(manifest))

    def test_progress_reports_bytes_and_total(self):
        with tempfile.TemporaryDirectory() as td:
            image = Path(td) / "disk.img"
            image.write_bytes(b"x" * 10000)
            seen = []
            result = verify_image(image, chunk_size=1024, progress=lambda done, total: seen.append((done, total)))
            self.assertEqual(result.size, 10000)
            self.assertTrue(seen)
            self.assertEqual(seen[-1], (10000, 10000))

    def test_known_source_size_rejects_incomplete_image(self):
        with tempfile.TemporaryDirectory() as td:
            image = Path(td) / "disk.img"
            image.write_bytes(b"x" * 9000)
            c = RecoveryCoordinator(RecoverySession(source_identified=True, source_assessed=True, source_size=10000))
            with self.assertRaises(ValueError):
                c.attach_completed_image(image, device_id="disk-8")
            self.assertFalse(c.session.image_complete)

    def test_cancelled_verification_never_marks_session_verified(self):
        with tempfile.TemporaryDirectory() as td:
            image = Path(td) / "disk.img"
            image.write_bytes(b"x" * 10000)
            c = RecoveryCoordinator(RecoverySession(source_identified=True, source_assessed=True))
            c.attach_completed_image(image, device_id="disk-image")
            calls = {"n": 0}
            def cancel():
                calls["n"] += 1
                return calls["n"] > 1
            with self.assertRaises(VerificationCancelled):
                c.verify_attached_image(should_cancel=cancel)
            self.assertFalse(c.session.image_verified)
            self.assertEqual(c.session.image_sha256, "")
            self.assertIsNone(c.last_manifest)

    def test_session_roundtrip_preserves_gates(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "session.json"
            session = RecoverySession(source_label="Disk 3", source_identified=True, source_assessed=True, image_path="D:/disk.img")
            session.save(path)
            loaded = RecoverySession.load(path)
            self.assertEqual(loaded.source_label, "Disk 3")
            self.assertTrue(loaded.plan_state().source_assessed)
            self.assertFalse(loaded.plan_state().image_verified)


if __name__ == "__main__":
    unittest.main()
