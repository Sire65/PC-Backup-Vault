import inspect
import unittest

from archive_restore_v198 import _emit, _manifest_total_bytes, restore_archived_job
from restore_progress_v1910 import format_bytes, format_duration


class RestoreProgressV1910Tests(unittest.TestCase):
    def test_duration_format(self):
        self.assertEqual(format_duration(0), "00:00")
        self.assertEqual(format_duration(65), "01:05")
        self.assertEqual(format_duration(3661), "01:01:01")
        self.assertEqual(format_duration(None), "–")

    def test_bytes_format(self):
        self.assertEqual(format_bytes(0), "0.0 B")
        self.assertEqual(format_bytes(1024), "1.0 KB")
        self.assertEqual(format_bytes(5 * 1024 * 1024), "5.0 MB")

    def test_manifest_total_bytes(self):
        manifest = {"files": [{"original_size": 100}, {"original_size": 250}, {"original_size": None}]}
        self.assertEqual(_manifest_total_bytes(manifest), 350)

    def test_progress_callback_is_additive_and_backward_compatible(self):
        self.assertIn("progress", inspect.signature(restore_archived_job).parameters)
        events = []
        _emit(events.append, phase="test", files_done=1, files_total=2, bytes_done=10, bytes_total=20, current_file="a.txt")
        self.assertEqual(events[0]["phase"], "test")
        self.assertEqual(events[0]["bytes_total"], 20)

    def test_progress_callback_failure_never_breaks_restore_path(self):
        def bad(_info):
            raise RuntimeError("UI closed")
        _emit(bad, phase="test", files_done=0, files_total=1, bytes_done=0, bytes_total=1, current_file="x")


if __name__ == "__main__":
    unittest.main()
