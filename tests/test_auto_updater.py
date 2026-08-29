from __future__ import annotations

import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import auto_updater


class _Response(io.BytesIO):
    def __init__(self, data: bytes):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


class AutoUpdaterTests(unittest.TestCase):
    def test_semver_comparison(self):
        self.assertTrue(auto_updater.is_newer_version("1.7.3", "1.8.0"))
        self.assertFalse(auto_updater.is_newer_version("1.8.0", "1.8.0"))
        self.assertFalse(auto_updater.is_newer_version("1.8.1", "1.8.0"))
        with self.assertRaises(ValueError):
            auto_updater.is_newer_version("1.8", "1.8.0")

    def test_release_requires_matching_setup_and_checksum(self):
        release = {
            "draft": False,
            "prerelease": False,
            "tag_name": "v1.8.0",
            "html_url": "https://github.com/Sire65/PC-Backup-Vault/releases/tag/v1.8.0",
            "body": "Release",
            "assets": [
                {
                    "name": "PC_Backup_Vault_1.8.0_Setup.exe",
                    "browser_download_url": "https://github.com/Sire65/PC-Backup-Vault/releases/download/v1.8.0/PC_Backup_Vault_1.8.0_Setup.exe",
                    "size": 123,
                },
                {
                    "name": "PC_Backup_Vault_1.8.0_Setup.exe.sha256",
                    "browser_download_url": "https://github.com/Sire65/PC-Backup-Vault/releases/download/v1.8.0/PC_Backup_Vault_1.8.0_Setup.exe.sha256",
                    "size": 90,
                },
            ],
        }
        with patch.object(auto_updater, "_get_json", return_value=release):
            info = auto_updater.fetch_latest_release("1.7.3")
        self.assertIsNotNone(info)
        self.assertEqual(info.version, "1.8.0")
        self.assertEqual(info.setup_name, "PC_Backup_Vault_1.8.0_Setup.exe")

        release["assets"] = release["assets"][:1]
        with patch.object(auto_updater, "_get_json", return_value=release):
            self.assertIsNone(auto_updater.fetch_latest_release("1.7.3"))

    def test_download_is_published_only_after_sha256_match(self):
        payload = b"verified setup bytes"
        expected = hashlib.sha256(payload).hexdigest()
        info = auto_updater.ReleaseInfo(
            version="1.8.0",
            tag="v1.8.0",
            setup_name="PC_Backup_Vault_1.8.0_Setup.exe",
            setup_url="https://github.com/Sire65/PC-Backup-Vault/releases/download/v1.8.0/PC_Backup_Vault_1.8.0_Setup.exe",
            setup_size=len(payload),
            sha256_name="PC_Backup_Vault_1.8.0_Setup.exe.sha256",
            sha256_url="https://github.com/Sire65/PC-Backup-Vault/releases/download/v1.8.0/PC_Backup_Vault_1.8.0_Setup.exe.sha256",
            release_url="https://github.com/Sire65/PC-Backup-Vault/releases/tag/v1.8.0",
        )
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(auto_updater, "fetch_expected_sha256", return_value=expected), patch(
                "auto_updater.urllib.request.urlopen", return_value=_Response(payload)
            ):
                path = auto_updater.download_and_verify(info, target_dir=tmp)
            self.assertEqual(path.read_bytes(), payload)
            self.assertFalse(Path(str(path) + ".part").exists())

    def test_bad_checksum_leaves_existing_install_untouched(self):
        payload = b"tampered bytes"
        info = auto_updater.ReleaseInfo(
            version="1.8.0",
            tag="v1.8.0",
            setup_name="PC_Backup_Vault_1.8.0_Setup.exe",
            setup_url="https://github.com/Sire65/PC-Backup-Vault/releases/download/v1.8.0/PC_Backup_Vault_1.8.0_Setup.exe",
            setup_size=len(payload),
            sha256_name="PC_Backup_Vault_1.8.0_Setup.exe.sha256",
            sha256_url="https://github.com/Sire65/PC-Backup-Vault/releases/download/v1.8.0/PC_Backup_Vault_1.8.0_Setup.exe.sha256",
            release_url="https://github.com/Sire65/PC-Backup-Vault/releases/tag/v1.8.0",
        )
        with tempfile.TemporaryDirectory() as tmp:
            final = Path(tmp) / info.setup_name
            with patch.object(auto_updater, "fetch_expected_sha256", return_value="0" * 64), patch(
                "auto_updater.urllib.request.urlopen", return_value=_Response(payload)
            ):
                with self.assertRaises(RuntimeError):
                    auto_updater.download_and_verify(info, target_dir=tmp)
            self.assertFalse(final.exists())
            self.assertFalse(Path(str(final) + ".part").exists())


if __name__ == "__main__":
    unittest.main()
