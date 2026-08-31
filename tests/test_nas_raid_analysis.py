import tempfile
import unittest
from pathlib import Path

from nas_recovery.raid_analysis import assess_image_set, inspect_image, render_worksheet, save_worksheet


class RaidImageAnalysisTests(unittest.TestCase):
    def make_image(self, root: Path, name: str, *, size: int = 2 * 1024 * 1024, mbr: bool = True):
        data = bytearray(size)
        if mbr and size >= 512:
            data[510:512] = b"\x55\xaa"
        path = root / name
        path.write_bytes(data)
        return path

    def test_inspection_is_read_only_and_detects_mbr(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            image = self.make_image(root, "member1.img")
            before = image.read_bytes()
            result = inspect_image(image)
            after = image.read_bytes()
            self.assertEqual(before, after)
            self.assertIn("MBR", result.signatures)
            self.assertEqual(result.size, len(before))
            self.assertEqual(len(result.sha256_first_mib), 64)

    def test_same_size_set_is_reported(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            a = self.make_image(root, "a.img")
            b = self.make_image(root, "b.img")
            result = assess_image_set([a, b])
            self.assertTrue(result.same_size)
            self.assertEqual(result.size_spread, 0)
            self.assertEqual(len(result.images), 2)

    def test_different_sizes_are_not_treated_as_proof_of_raid(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            a = self.make_image(root, "a.img", size=2 * 1024 * 1024)
            b = self.make_image(root, "b.img", size=3 * 1024 * 1024)
            result = assess_image_set([a, b])
            self.assertFalse(result.same_size)
            self.assertGreater(result.size_spread, 0)
            self.assertIn("unterschiedlichen Größen", result.summary)

    def test_worksheet_contains_safety_rule_and_atomic_save(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            image = self.make_image(root, "a.img")
            result = assess_image_set([image])
            text = render_worksheet(result)
            self.assertIn("Keine Rekonstruktion auf Originalplatten schreiben", text)
            target = root / "report.txt"
            saved = save_worksheet(target, text)
            self.assertEqual(saved, target.resolve())
            self.assertEqual(target.read_text(encoding="utf-8"), text)
            self.assertFalse((root / "report.txt.tmp").exists())

    def test_physicaldrive_named_path_is_blocked(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            image = self.make_image(root, "PhysicalDrive0.img")
            with self.assertRaises(ValueError):
                inspect_image(image)


if __name__ == "__main__":
    unittest.main()
