import unittest
from unittest.mock import patch

from project_finder import runner_entry


class RunnerEntryTests(unittest.TestCase):
    def test_runner_calls_analysis_job_and_returns_success(self):
        with patch.object(runner_entry, "run_job", return_value={"status": "SUCCESS"}) as run_job:
            code = runner_entry.main(["--profile", "night.json"])
        self.assertEqual(code, 0)
        run_job.assert_called_once_with("night.json")

    def test_runner_returns_nonzero_on_failure(self):
        with patch.object(runner_entry, "run_job", side_effect=RuntimeError("boom")):
            code = runner_entry.main(["--profile", "night.json"])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
