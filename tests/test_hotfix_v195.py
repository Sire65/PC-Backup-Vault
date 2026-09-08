from __future__ import annotations

import unittest
from unittest.mock import patch
import urllib.error

import hotfix_v195


class _Button:
    def __init__(self):
        self.text = "Backup starten"
        self.command = None
        self.master = _Parent(self)
    def configure(self, **kwargs):
        self.text = kwargs.get("text", self.text)
        self.command = kwargs.get("command", self.command)


class _Parent:
    def __init__(self, button):
        self.button = button
    def winfo_children(self):
        return [self.button]


class _App:
    def __init__(self):
        self.btn_backup = _Button()


class HotfixV195Tests(unittest.TestCase):
    def _release(self, version="1.9.5"):
        setup = f"PC_Backup_Vault_{version}_Setup.exe"
        return {
            "draft": False,
            "prerelease": False,
            "tag_name": f"v{version}",
            "html_url": f"https://github.com/Sire65/PC-Backup-Vault/releases/tag/v{version}",
            "assets": [
                {"name": setup, "browser_download_url": f"https://github.com/Sire65/PC-Backup-Vault/releases/download/v{version}/{setup}", "size": 42},
                {"name": setup + ".sha256", "browser_download_url": f"https://github.com/Sire65/PC-Backup-Vault/releases/download/v{version}/{setup}.sha256", "size": 99},
            ],
        }

    def test_primary_backup_button_opens_workbench(self):
        app = _App()
        opened = []
        class Workbench:
            def __init__(self, owner): opened.append(owner)
        self.assertTrue(hotfix_v195.configure_primary_backup_entry(app, Workbench))
        self.assertEqual(app.btn_backup.text, "⇄ Sichern & Wiederherstellen")
        app.btn_backup.command()
        self.assertEqual(opened, [app])

    def test_release_parser_finds_new_verified_release(self):
        info = hotfix_v195.release_from_payload("1.9.4", self._release())
        self.assertIsNotNone(info)
        self.assertEqual(info.version, "1.9.5")
        self.assertEqual(info.setup_name, "PC_Backup_Vault_1.9.5_Setup.exe")

    def test_release_parser_returns_none_when_current(self):
        self.assertIsNone(hotfix_v195.release_from_payload("1.9.5", self._release()))

    def test_connection_failure_is_not_reported_as_current(self):
        with patch("hotfix_v195.auto_updater._get_json", side_effect=urllib.error.URLError("offline")):
            with self.assertRaisesRegex(RuntimeError, "Update-Server konnte nicht erreicht werden"):
                hotfix_v195.fetch_latest_release_strict("1.9.4")


if __name__ == "__main__":
    unittest.main()
