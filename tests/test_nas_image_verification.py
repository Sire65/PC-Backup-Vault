import tempfile
import unittest
from pathlib import Path

from nas_recovery.image_verification import manifest_matches_image, verify_image, write_manifest
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
