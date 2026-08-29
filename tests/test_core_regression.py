from __future__ import annotations

import hashlib
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import backup_engine


class CoreBackupRegressionTests(unittest.TestCase):
    def test_backup_control_pause_resume_cancel(self):
        control = backup_engine.BackupControl()
        self.assertFalse(control.paused)
        self.assertFalse(control.cancelled)

        control.pause()
        self.assertTrue(control.paused)

        released = threading.Event()
        errors = []

        def worker():
            try:
                control.check()
                released.set()
            except Exception as exc:  # pragma: no cover - diagnostic path
                errors.append(exc)

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        time.sleep(0.05)
        self.assertFalse(released.is_set())
        control.resume()
        thread.join(1.0)
        self.assertTrue(released.is_set())
        self.assertEqual(errors, [])

        control.cancel()
        self.assertTrue(control.cancelled)
        with self.assertRaises(backup_engine.BackupCancelled):
            control.check()

    def test_collect_paths_deduplicates_and_hashes_exactly(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nested = root / "data"
            nested.mkdir()
            a = nested / "a.txt"
            b = nested / "b.bin"
            a.write_text("backup-vault", encoding="utf-8")
            b.write_bytes(b"\x00\x01\x02")

            rows = backup_engine.collect_paths([str(nested), str(a)])
            self.assertEqual({p.name for p in rows}, {"a.txt", "b.bin"})
            self.assertEqual(
                backup_engine.file_sha256(a),
                hashlib.sha256(b"backup-vault").hexdigest(),
            )

    def test_compression_policy_keeps_already_compressed_files_raw(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "archive.zip"
            p.write_bytes(b"not-a-real-zip-but-extension-is-policy-relevant")
            self.assertEqual(backup_engine.choose_compression(p), "NONE")

    def test_payload_target_auto_neon_without_b2(self):
        with mock.patch("backup_engine.make_b2_store", return_value=None):
            target, store = backup_engine.resolve_payload_target("AUTO", {"configured": False})
        self.assertEqual(target, "NEON")
        self.assertIsNone(store)

    def test_payload_target_auto_prefers_b2_when_configured(self):
        sentinel = object()
        with mock.patch("backup_engine.make_b2_store", return_value=sentinel):
            target, store = backup_engine.resolve_payload_target("AUTO", {"configured": True})
        self.assertEqual(target, "B2")
        self.assertIs(store, sentinel)

    def test_explicit_b2_without_configuration_is_blocked(self):
        with mock.patch("backup_engine.make_b2_store", return_value=None):
            with self.assertRaises(ValueError):
                backup_engine.resolve_payload_target("B2", {"configured": False})

    def test_upload_worker_count_is_bounded(self):
        self.assertEqual(backup_engine._upload_worker_count({"upload_workers": 0}), 1)
        self.assertEqual(backup_engine._upload_worker_count({"upload_workers": 99}), 8)
        self.assertEqual(backup_engine._upload_worker_count({"upload_workers": 4}), 4)


if __name__ == "__main__":
    unittest.main()
