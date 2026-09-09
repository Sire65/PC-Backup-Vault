import io
import stat
import unittest

from context_progress_v1917 import _copy_stream, _remote_manifest, format_bytes, format_duration
from context_progress_safety_v1917 import _collect_delete_manifest


class Attr:
    def __init__(self, filename, mode, size=0):
        self.filename = filename
        self.st_mode = mode
        self.st_size = size
        self.st_mtime = 0


class FakeSftp:
    def __init__(self, children):
        self.children = children

    def listdir_attr(self, path):
        return list(self.children.get(path, []))


class ContextProgressTests(unittest.TestCase):
    def test_format_helpers(self):
        self.assertEqual("1.0 KB", format_bytes(1024))
        self.assertEqual("01:05", format_duration(65))
        self.assertEqual("01:01:01", format_duration(3661))

    def test_remote_manifest_counts_nested_files_and_bytes(self):
        sftp = FakeSftp({
            "/users/u/A": [
                Attr("one.bin", stat.S_IFREG | 0o644, 10),
                Attr("sub", stat.S_IFDIR | 0o755),
            ],
            "/users/u/A/sub": [
                Attr("two.bin", stat.S_IFREG | 0o644, 25),
            ],
        })
        rows = [{"name": "A", "path": "/users/u/A", "is_dir": True, "size": 0}]
        files, dirs, total = _remote_manifest(sftp, rows)
        self.assertEqual(35, total)
        self.assertEqual(["A", "A/sub"], dirs)
        self.assertEqual(
            ["/users/u/A/one.bin", "/users/u/A/sub/two.bin"],
            [x["remote"] for x in files],
        )
        self.assertEqual(["A/one.bin", "A/sub/two.bin"], [x["rel"] for x in files])

    def test_delete_manifest_keeps_exact_paths_for_duplicate_folder_names(self):
        sftp = FakeSftp({
            "/users/u/A": [Attr("same", stat.S_IFDIR | 0o755)],
            "/users/u/A/same": [Attr("a.txt", stat.S_IFREG | 0o644, 5)],
            "/users/u/B": [Attr("same", stat.S_IFDIR | 0o755)],
            "/users/u/B/same": [Attr("b.txt", stat.S_IFREG | 0o644, 7)],
        })
        rows = [
            {"name": "A", "path": "/users/u/A", "is_dir": True, "size": 0},
            {"name": "B", "path": "/users/u/B", "is_dir": True, "size": 0},
        ]
        files, dirs, total = _collect_delete_manifest(sftp, rows)
        self.assertEqual(12, total)
        self.assertIn("/users/u/A/same", dirs)
        self.assertIn("/users/u/B/same", dirs)
        self.assertIn("/users/u/A/same/a.txt", [x["remote"] for x in files])
        self.assertIn("/users/u/B/same/b.txt", [x["remote"] for x in files])

    def test_copy_stream_reports_real_byte_progress(self):
        source = io.BytesIO(b"x" * 700000)
        target = io.BytesIO()
        samples = []
        copied = _copy_stream(source, target, 700000, lambda done, total: samples.append((done, total)))
        self.assertEqual(700000, copied)
        self.assertEqual(700000, len(target.getvalue()))
        self.assertGreaterEqual(len(samples), 3)
        self.assertEqual((700000, 700000), samples[-1])
        self.assertEqual(sorted(x[0] for x in samples), [x[0] for x in samples])


if __name__ == "__main__":
    unittest.main()
