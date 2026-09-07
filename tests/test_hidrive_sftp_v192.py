import tempfile
import unittest
from pathlib import Path
from unittest import mock

import hidrive_sftp_v192 as hidrive


class HiDriveSftpTests(unittest.TestCase):
    def test_default_root_uses_hidrive_user(self):
        self.assertEqual(hidrive._root({"username": "sire25", "root_path": ""}), "/users/sire25")

    def test_explicit_root_is_normalized_absolute(self):
        self.assertEqual(
            hidrive._root({"username": "sire25", "root_path": "/users/sire25/PC_Backup_Vault"}),
            "/users/sire25/PC_Backup_Vault",
        )

    def test_host_port_defaults_to_strato_22(self):
        with mock.patch.object(hidrive, "effective_endpoint", return_value="sftp.hidrive.strato.com"):
            self.assertEqual(hidrive._host_port({}), ("sftp.hidrive.strato.com", 22))

    def test_strict_client_refuses_missing_known_hosts(self):
        with mock.patch.object(hidrive, "_known_hosts_files", return_value=iter(())):
            with self.assertRaisesRegex(RuntimeError, "Vertrauensspeicher"):
                hidrive._strict_client("sftp.hidrive.strato.com", 22, "user", "secret")

    def test_write_bytes_creates_parent_and_writes_payload(self):
        class FakeFile:
            def __init__(self):
                self.data = b""
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def write(self, data): self.data += data
            def flush(self): pass

        class FakeSftp:
            def __init__(self):
                self.files = {}
                self.dirs = {"/"}
            def stat(self, path):
                if path not in self.dirs:
                    raise OSError(path)
                return object()
            def mkdir(self, path): self.dirs.add(path)
            def file(self, path, mode):
                fh = FakeFile()
                self.files[path] = fh
                return fh

        sftp = FakeSftp()
        hidrive._write_bytes(sftp, "/users/sire25/PC_Backup_Vault/test.bin", b"abc")
        self.assertIn("/users/sire25/PC_Backup_Vault/test.bin", sftp.files)
        self.assertEqual(sftp.files["/users/sire25/PC_Backup_Vault/test.bin"].data, b"abc")


if __name__ == "__main__":
    unittest.main()
