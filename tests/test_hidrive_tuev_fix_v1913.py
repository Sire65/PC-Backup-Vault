import hashlib
import io
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest import mock

from crypto_box import create_key_b64, encrypt_bytes, sha256_bytes
import hidrive_tuev_fix_v1913 as fix


class FakeSftp:
    def __init__(self, files=None):
        self.files = dict(files or {})

    def listdir_attr(self, path):
        prefix = path.rstrip("/") + "/"
        names = []
        for key in self.files:
            if key.startswith(prefix):
                rest = key[len(prefix):]
                if "/" not in rest and rest.endswith(".json"):
                    names.append(SimpleNamespace(filename=rest, st_mtime=100))
        return names

    def stat(self, path):
        if path not in self.files:
            raise OSError(path)
        return SimpleNamespace(st_size=len(self.files[path]))

    def file(self, path, mode):
        if "r" not in mode or path not in self.files:
            raise OSError(path)
        return io.BytesIO(self.files[path])


class Store:
    def __init__(self, account):
        self.data = {
            "cloud_accounts": [account],
            "restore_selftest_max_kb": 256,
        }


class HiDriveTuevFixTests(unittest.TestCase):
    def setUp(self):
        self.account = {
            "id": "acc-1",
            "name": "Strato_test",
            "username": "test",
            "root_path": "/users/test/PC_Backup_Vault",
        }
        self.target = {
            "id": "cloud-acc-1",
            "name": "Cloud · Strato_test",
            "kind": "CLOUD-SFTP",
            "cloud_method": "SFTP",
            "cloud_account_id": "acc-1",
            "path": "/users/test/PC_Backup_Vault",
        }

    def test_hidrive_target_is_not_local_filesystem(self):
        self.assertTrue(fix._is_hidrive_target(self.target))
        self.assertFalse(fix._is_hidrive_target({"kind": "NAS", "path": r"\\server\backup"}))

    def test_remote_hidrive_backup_and_restore_probe_pass(self):
        key = create_key_b64()
        raw = b"PC Backup Vault remote restore probe"
        file_sha = hashlib.sha256(raw).hexdigest()
        nonce, cipher = encrypt_bytes(key, raw, f"{file_sha}:0".encode("ascii"))
        rel = f"{file_sha[:2]}/{file_sha}/000000-test.bin"
        manifest = {
            "format": "PCBV-FS-1",
            "files": [{
                "sha256": file_sha,
                "original_size": len(raw),
                "chunks": [{"no": 0, "file": rel, "cipher_sha256": sha256_bytes(cipher)}],
            }],
        }
        root = self.account["root_path"] + "/.pc-backup-vault"
        files = {
            root + "/jobs/job-1.json": __import__("json").dumps(manifest).encode("utf-8"),
            root + "/chunks/" + rel: nonce + cipher,
        }
        sftp = FakeSftp(files)

        @contextmanager
        def connection(_store, _account_id):
            yield sftp, dict(self.account)

        store = Store(self.account)
        with mock.patch.object(fix, "test_hidrive_sftp", return_value=(True, "ok")), \
             mock.patch.object(fix, "sftp_connection", side_effect=connection):
            checks = fix._hidrive_checks(store, key, self.target, 2)

        self.assertEqual([c[0] for c in checks], ["FS-002", "FSV-002", "FSR-002"])
        self.assertEqual([c[2] for c in checks], ["PASS", "PASS", "PASS"])
        self.assertIn("SHA-256 PASS", checks[-1][3])

    def test_connected_hidrive_without_backup_is_warning_not_fake_local_pass(self):
        store = Store(self.account)
        sftp = FakeSftp()

        @contextmanager
        def connection(_store, _account_id):
            yield sftp, dict(self.account)

        with mock.patch.object(fix, "test_hidrive_sftp", return_value=(True, "ok")), \
             mock.patch.object(fix, "sftp_connection", side_effect=connection):
            checks = fix._hidrive_checks(store, create_key_b64(), self.target, 3)

        self.assertEqual(checks[0][2], "PASS")
        self.assertEqual(checks[1][2], "WARN")
        self.assertIn("HiDrive-Backup-Stand", checks[1][3])


if __name__ == "__main__":
    unittest.main()
