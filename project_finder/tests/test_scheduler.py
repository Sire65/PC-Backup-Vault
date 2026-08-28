import unittest
from pathlib import Path
from unittest.mock import patch

from project_finder.scheduler import resolve_runner_command


class SchedulerTests(unittest.TestCase):
    def test_source_mode_uses_python_module_runner(self):
        cmd = resolve_runner_command(r"C:\Jobs\nacht.json", frozen=False)
        self.assertIn("-m project_finder.job_runner", cmd)
        self.assertIn("nacht.json", cmd)

    def test_explicit_runner_is_used_in_packaged_mode(self):
        cmd = resolve_runner_command(
            r"C:\Jobs\nacht.json",
            r"C:\Program Files\PC Backup Vault\ProjectFinderRunner.exe",
            frozen=True,
        )
        self.assertIn("ProjectFinderRunner.exe", cmd)
        self.assertIn("--profile", cmd)

    def test_packaged_mode_never_falls_back_to_backup_gui(self):
        with patch.object(Path, "exists", return_value=False):
            with self.assertRaises(RuntimeError):
                resolve_runner_command(r"C:\Jobs\nacht.json", frozen=True)


if __name__ == "__main__":
    unittest.main()
