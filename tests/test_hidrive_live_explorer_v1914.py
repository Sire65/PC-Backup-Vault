import stat
import unittest

import hidrive_live_explorer_v1914 as live


class FakeAttr:
    def __init__(self, filename, is_dir=False, size=0, mtime=0):
        self.filename = filename
        self.st_mode = (stat.S_IFDIR | 0o755) if is_dir else (stat.S_IFREG | 0o644)
        self.st_size = size
        self.st_mtime = mtime


class FakeSftp:
    def __init__(self):
        self.entries = {
            "/users/demo": [FakeAttr("B.txt", False, 20), FakeAttr("Ordner", True), FakeAttr("a.txt", False, 10)],
            "/users/demo/Ordner": [FakeAttr("innen.txt", False, 5)],
        }
        self.files = {"/users/demo/B.txt", "/users/demo/a.txt", "/users/demo/Ordner/innen.txt"}
        self.dirs = {"/users/demo", "/users/demo/Ordner"}
        self.removed = []
        self.rmdirs = []

    def listdir_attr(self, path):
        if path not in self.entries:
            raise OSError(path)
        return list(self.entries[path])

    def stat(self, path):
        if path in self.dirs:
            return FakeAttr(path.rsplit("/", 1)[-1], True)
        if path in self.files:
            return FakeAttr(path.rsplit("/", 1)[-1], False, 5)
        raise OSError(path)

    def remove(self, path):
        self.removed.append(path)
        self.files.remove(path)

    def rmdir(self, path):
        self.rmdirs.append(path)
        self.dirs.remove(path)


class HiDriveLiveExplorerTests(unittest.TestCase):
    def test_home_uses_full_user_area_not_backup_root(self):
        account = {"username": "hausmeister1", "root_path": "/users/hausmeister1/PC_Backup_Vault"}
        self.assertEqual(live._home(account), "/users/hausmeister1")

    def test_remote_normalization(self):
        self.assertEqual(live._norm_remote(r"users\demo\Ordner"), "/users/demo/Ordner")
        self.assertEqual(live._norm_remote("/users/demo/../demo/a"), "/users/demo/a")

    def test_within_blocks_parent_escape(self):
        self.assertTrue(live._within("/users/demo/A", "/users/demo"))
        self.assertTrue(live._within("/users/demo", "/users/demo"))
        self.assertFalse(live._within("/users/other", "/users/demo"))

    def test_backup_vault_is_recognized_as_protected(self):
        home = "/users/demo"
        self.assertTrue(live._is_protected("/users/demo/.pc-backup-vault", home))
        self.assertTrue(live._is_protected("/users/demo/.pc-backup-vault/jobs/1.json", home))
        self.assertFalse(live._is_protected("/users/demo/Urlaub/Bild.jpg", home))

    def test_listing_sorts_folders_first_then_names(self):
        rows = live._list_remote(FakeSftp(), "/users/demo")
        self.assertEqual([r["name"] for r in rows], ["Ordner", "a.txt", "B.txt"])
        self.assertTrue(rows[0]["is_dir"])
        self.assertEqual(rows[1]["size"], 10)

    def test_recursive_delete_removes_children_before_folder(self):
        sftp = FakeSftp()
        live._delete_remote(sftp, "/users/demo/Ordner")
        self.assertEqual(sftp.removed, ["/users/demo/Ordner/innen.txt"])
        self.assertEqual(sftp.rmdirs, ["/users/demo/Ordner"])

    def test_hidrive_account_filter_requires_strato_and_sftp(self):
        class Store:
            def __init__(self):
                self.data = {"cloud_accounts": [
                    {"id": "1", "provider_code": "STRATO_HIDRIVE", "methods": ["SFTP"], "preferred_method": "SFTP"},
                    {"id": "2", "provider_code": "STRATO_HIDRIVE", "methods": ["WEBDAV"], "preferred_method": "WEBDAV"},
                    {"id": "3", "provider_code": "GENERIC_SFTP", "methods": ["SFTP"], "preferred_method": "SFTP"},
                ]}
            def save(self):
                pass
        self.assertEqual([a["id"] for a in live._hidrive_accounts(Store())], ["1"])


if __name__ == "__main__":
    unittest.main()
