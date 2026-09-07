import unittest
from pathlib import Path

from restore_path_fix_v188 import safe_relative_restore_path


class RestorePathFixTests(unittest.TestCase):
    def test_drive_path_stays_relative(self):
        rel = safe_relative_restore_path(r"C:\One_Drive\OneDrive\Dokumente", "ThönnißenRE-25-10-2309.pdf")
        self.assertFalse(rel.is_absolute())
        self.assertEqual(rel.parts[0], "C")
        self.assertEqual(rel.name, "ThönnißenRE-25-10-2309.pdf")
        root = Path("restore-root")
        final = root / rel
        self.assertEqual(final.relative_to(root), rel)

    def test_unc_path_stays_relative(self):
        rel = safe_relative_restore_path(r"\\NAS01\Backup\KC\Dokumente", "test.pdf")
        self.assertFalse(rel.is_absolute())
        self.assertEqual(rel.parts[0], "UNC")
        self.assertEqual(rel.name, "test.pdf")

    def test_filename_cannot_escape_restore_root(self):
        rel = safe_relative_restore_path(r"C:\Daten", r"..\..\boese.pdf")
        self.assertFalse(rel.is_absolute())
        self.assertEqual(rel.name, "boese.pdf")


if __name__ == "__main__":
    unittest.main()
