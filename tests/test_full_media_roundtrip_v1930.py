from __future__ import annotations

import hashlib
import io
import json
import posixpath
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import backup_engine
import hidrive_sftp_v192
from archive_restore_v198 import _restore_manifest_local, _restore_manifest_sftp
from crypto_box import create_key_b64, decrypt_bytes, encrypt_bytes, encrypt_text, sha256_bytes
from storage_v180 import VAULT_DIR, filesystem_backup


class _App:
    def __init__(self):
        self._key = create_key_b64()
        self.store = SimpleNamespace(data={})

    def master_key(self):
        return self._key


class _WriteBuffer(io.BytesIO):
    def __init__(self, sftp, path):
        super().__init__()
        self._sftp = sftp
        self._path = path

    def close(self):
        if not self.closed:
            self._sftp.files[self._path] = self.getvalue()
        super().close()


class FakeSFTP:
    """Small in-memory SFTP used to exercise the real HiDrive transport code."""

    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.dirs = {"/"}

    @staticmethod
    def _p(path):
        p = posixpath.normpath(str(path))
        return p if p.startswith("/") else "/" + p

    def stat(self, path):
        p = self._p(path)
        if p in self.dirs or p in self.files:
            return SimpleNamespace()
        raise OSError(p)

    def mkdir(self, path):
        self.dirs.add(self._p(path))

    def chdir(self, _path):
        return None

    def file(self, path, mode):
        p = self._p(path)
        if "w" in mode:
            return _WriteBuffer(self, p)
        if p not in self.files:
            raise OSError(p)
        return io.BytesIO(self.files[p])

    def remove(self, path):
        self.files.pop(self._p(path), None)

    def posix_rename(self, old, new):
        self.files[self._p(new)] = self.files.pop(self._p(old))

    rename = posix_rename


class FakeRestoreConn:
    def __init__(self, file_row, chunks):
        self.file_row = file_row
        self.chunks = chunks
        self.last_sql = ""
        self.restore_inserts = []
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.last_sql = " ".join(str(sql).split()).lower()
        if self.last_sql.startswith("insert into backup_vault.restore_tests"):
            self.restore_inserts.append(params)
        return self

    def fetchone(self):
        if "from backup_vault.files where id=" in self.last_sql:
            return self.file_row
        return None

    def fetchall(self):
        if "from backup_vault.file_chunks" in self.last_sql:
            return self.chunks
        return []

    def commit(self):
        self.commits += 1


class FakeRestoreB2:
    def __init__(self, objects):
        self.objects = dict(objects)

    def get(self, key):
        return self.objects[key]


def _restored_file(root: Path, name: str) -> Path:
    matches = list(root.rglob(name))
    if len(matches) != 1:
        raise AssertionError(f"Erwartet genau eine wiederhergestellte Datei {name}, gefunden: {matches}")
    return matches[0]


class FullMediaRoundtrip1930Tests(unittest.TestCase):
    def test_local_filesystem_backup_restore_roundtrip_and_corruption_stop(self):
        app = _App()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "quelle"
            source.mkdir()
            (source / "bericht.txt").write_text("PC Backup Vault TÜV – lokal", encoding="utf-8")
            (source / "daten.bin").write_bytes(bytes(range(256)) * 64)
            target_root = root / "ziel"
            target_root.mkdir()
            target = {"id": "local", "name": "TÜV lokal", "path": str(target_root), "kind": "ORDNER"}

            result = filesystem_backup(app, [source], target)
            self.assertEqual(result["status"], "SUCCESS")
            self.assertEqual(result["files"], 2)

            vault = target_root / VAULT_DIR
            manifest_path = vault / "jobs" / f"{result['job_id']}.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["format"], "PCBV-FS-1")
            self.assertTrue(all(str(x["path"]).startswith("enc:v1:") for x in manifest["files"]))
            self.assertTrue(all(str(x["name"]).startswith("enc:v1:") for x in manifest["files"]))

            restore_dir = root / "restore"
            restored = _restore_manifest_local(app, manifest, vault, restore_dir)
            self.assertEqual(restored["files"], 2)
            self.assertEqual(_restored_file(restore_dir, "bericht.txt").read_text(encoding="utf-8"), "PC Backup Vault TÜV – lokal")
            self.assertEqual(_restored_file(restore_dir, "daten.bin").read_bytes(), bytes(range(256)) * 64)

            # Manipulated encrypted backup data must never be restored silently.
            ref = manifest["files"][0]["chunks"][0]
            chunk = vault / "chunks" / ref["file"]
            damaged = bytearray(chunk.read_bytes())
            damaged[-1] ^= 0x01
            chunk.write_bytes(bytes(damaged))
            with self.assertRaises(RuntimeError):
                _restore_manifest_local(app, manifest, vault, root / "restore-damaged")

    def test_drive_folder_and_nas_targets_use_verified_roundtrip_engine(self):
        app = _App()
        for kind in ("ORDNER", "LAUFWERK", "NAS"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                source = root / f"{kind.lower()}.txt"
                original = f"Roundtrip {kind}".encode("utf-8")
                source.write_bytes(original)
                target_root = root / "target"
                target_root.mkdir()
                result = filesystem_backup(app, [source], {"id": kind, "name": kind, "path": str(target_root), "kind": kind})
                vault = target_root / VAULT_DIR
                manifest = json.loads((vault / "jobs" / f"{result['job_id']}.json").read_text(encoding="utf-8"))
                restore_root = root / "restore"
                restored = _restore_manifest_local(app, manifest, vault, restore_root)
                self.assertEqual(restored["files"], 1)
                self.assertEqual(_restored_file(restore_root, source.name).read_bytes(), original)

    def test_hidrive_sftp_backup_restore_roundtrip(self):
        app = _App()
        fake = FakeSFTP()
        account = {
            "id": "acct-a",
            "name": "TÜV HiDrive",
            "username": "tuev-user",
            "root_path": "/users/tuev-user/PC_Backup_Vault",
        }
        target = {"name": "TÜV HiDrive", "cloud_account_id": "acct-a"}

        @contextmanager
        def connection(_store, account_id):
            self.assertEqual(account_id, "acct-a")
            yield fake, account

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "hidrive-test.txt"
            original = b"HiDrive SFTP Roundtrip\n" * 100
            source.write_bytes(original)
            with mock.patch("hidrive_sftp_v192.sftp_connection", connection):
                result = hidrive_sftp_v192.filesystem_backup_sftp(app, [source], target)

            self.assertEqual(result["status"], "SUCCESS")
            self.assertEqual(result["transport"], "SFTP")
            base = posixpath.join(hidrive_sftp_v192._root(account), hidrive_sftp_v192.VAULT_DIR)
            manifest_path = posixpath.join(base, "jobs", f"{result['job_id']}.json")
            manifest = json.loads(fake.files[manifest_path].decode("utf-8"))
            self.assertEqual(manifest["provider"], "STRATO_HIDRIVE")

            restore_dir = root / "restore-hidrive"
            restored = _restore_manifest_sftp(app, fake, account, manifest, restore_dir)
            self.assertEqual(restored["files"], 1)
            self.assertEqual(_restored_file(restore_dir, source.name).read_bytes(), original)

    def test_b2_encrypted_payload_roundtrip_and_integrity(self):
        class FakeB2:
            def __init__(self):
                self.objects = {}

            def object_key(self, sha, no):
                return f"pcbv/{sha}/{no:06d}.bin"

            def put(self, key, payload, expected_sha):
                self.assertion = sha256_bytes(payload) == expected_sha
                self.objects[key] = bytes(payload)
                return "etag-test"

        store = FakeB2()
        key = create_key_b64()
        uploaded = []
        import threading
        lock = threading.Lock()
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "b2.bin"
            original = (b"B2-Neon-Core-TUEV" * 4096) + bytes(range(64))
            source.write_bytes(original)
            file_sha = hashlib.sha256(original).hexdigest()
            result = backup_engine._upload_b2_file_worker(
                source, "NONE", file_sha, key, store, None, uploaded, lock
            )

        self.assertTrue(store.assertion)
        restored = bytearray()
        for no, nonce, cipher_sha, _size, object_key, _etag in result["chunks"]:
            cipher = store.objects[object_key]
            self.assertEqual(sha256_bytes(cipher), cipher_sha)
            aad = f"{file_sha}:{no}".encode("ascii")
            restored.extend(decrypt_bytes(key, nonce, cipher, aad))
        self.assertEqual(bytes(restored), original)
        self.assertEqual(hashlib.sha256(restored).hexdigest(), file_sha)

        # Cipher corruption is caught before decryption/restore.
        first = result["chunks"][0]
        damaged = bytearray(store.objects[first[4]])
        damaged[-1] ^= 1
        self.assertNotEqual(sha256_bytes(bytes(damaged)), first[2])

    def _database_restore_case(self, backend: str):
        key = create_key_b64()
        original = (f"{backend}-Restore über echte restore_file-Routine\n".encode("utf-8")) * 50
        file_sha = hashlib.sha256(original).hexdigest()
        nonce, cipher = encrypt_bytes(key, original, f"{file_sha}:0".encode("ascii"))
        cipher_sha = sha256_bytes(cipher)
        file_row = (
            "file-1", encrypt_text(key, f"{backend.lower()}-restore.txt"), file_sha,
            "NONE", "STORED", len(original), "job-1", backend,
        )
        object_key = "pcbv/test/object.bin" if backend == "B2" else None
        encrypted_data = None if backend == "B2" else cipher
        chunks = [(0, nonce, encrypted_data, cipher_sha, backend, object_key)]
        conn = FakeRestoreConn(file_row, chunks)
        b2 = FakeRestoreB2({object_key: cipher}) if backend == "B2" else None

        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(backup_engine.psycopg, "connect", return_value=conn), \
             mock.patch("backup_engine.make_b2_store", return_value=b2):
            dest = Path(tmp) / "restore"
            out = backup_engine.restore_file("test-dsn", key, "file-1", dest, object_store_config={})
            self.assertEqual(out.read_bytes(), original)
            self.assertEqual(hashlib.sha256(out.read_bytes()).hexdigest(), file_sha)
            self.assertFalse(list(dest.rglob("*.part")))
        self.assertTrue(conn.restore_inserts)
        self.assertGreaterEqual(conn.commits, 1)

    def test_neon_database_restore_real_codepath(self):
        self._database_restore_case("NEON")

    def test_b2_database_restore_real_codepath(self):
        self._database_restore_case("B2")

    def test_b2_restore_rejects_corrupted_object_and_removes_part_file(self):
        key = create_key_b64()
        original = b"B2 damaged restore test" * 100
        file_sha = hashlib.sha256(original).hexdigest()
        nonce, cipher = encrypt_bytes(key, original, f"{file_sha}:0".encode("ascii"))
        cipher_sha = sha256_bytes(cipher)
        damaged = bytearray(cipher)
        damaged[-1] ^= 1
        file_row = ("file-1", encrypt_text(key, "damaged.txt"), file_sha, "NONE", "STORED", len(original), "job-1", "B2")
        conn = FakeRestoreConn(file_row, [(0, nonce, None, cipher_sha, "B2", "obj")])
        b2 = FakeRestoreB2({"obj": bytes(damaged)})
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(backup_engine.psycopg, "connect", return_value=conn), \
             mock.patch("backup_engine.make_b2_store", return_value=b2):
            dest = Path(tmp) / "restore"
            with self.assertRaises(ValueError):
                backup_engine.restore_file("test-dsn", key, "file-1", dest, object_store_config={})
            self.assertFalse(list(dest.rglob("*.part")))

    def test_supported_backup_target_matrix_is_explicit(self):
        # B2 and Neon are the two database-backed payload choices.
        with mock.patch("backup_engine.make_b2_store", return_value=None):
            target, obj = backup_engine.resolve_payload_target("NEON", None)
            self.assertEqual((target, obj), ("NEON", None))
        sentinel = object()
        with mock.patch("backup_engine.make_b2_store", return_value=sentinel):
            target, obj = backup_engine.resolve_payload_target("B2", {})
            self.assertEqual(target, "B2")
            self.assertIs(obj, sentinel)

        # Supabase/PostgreSQL profiles are explorer/database connections, not backup payloads.
        with self.assertRaises(ValueError):
            backup_engine.resolve_payload_target("SUPABASE", None)
        with self.assertRaises(ValueError):
            backup_engine.resolve_payload_target("POSTGRESQL", None)


if __name__ == "__main__":
    unittest.main()
