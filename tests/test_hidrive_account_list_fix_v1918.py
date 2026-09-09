import unittest

from hidrive_account_list_fix_v1918 import eligible_hidrive_accounts


class Store:
    def __init__(self, data=None):
        self.data = data or {}


class HiDriveAccountListFixTests(unittest.TestCase):
    def test_legacy_strato_account_without_sftp_method_is_still_visible(self):
        rows = [
            {
                "id": "hausmeister",
                "name": "Strato_hausmeister1",
                "provider_code": "STRATO_HIDRIVE",
                "enabled": True,
                "methods": ["SFTP"],
                "preferred_method": "SFTP",
            },
            {
                "id": "sire25",
                "name": "Strato_sire25",
                "provider_code": "STRATO_HIDRIVE",
                "enabled": True,
                "methods": ["SMB"],
                "preferred_method": "SMB",
            },
        ]
        result = eligible_hidrive_accounts(Store(), lambda _store: rows)
        self.assertEqual([x["id"] for x in result], ["hausmeister", "sire25"])

    def test_real_legacy_record_without_provider_code_is_visible_by_strato_name(self):
        rows = [
            {
                "id": "sire25",
                "name": "Strato_sire25",
                "username": "sire25",
                "enabled": True,
                "root_path": "/users/sire25/PC_Backup_Vault",
            }
        ]
        store = Store({
            "filesystem_targets": [
                {
                    "kind": "CLOUD-SFTP",
                    "cloud_method": "SFTP",
                    "cloud_account_id": "sire25",
                    "path": "/users/sire25/PC_Backup_Vault",
                }
            ]
        })
        result = eligible_hidrive_accounts(store, lambda _store: rows)
        self.assertEqual([x["id"] for x in result], ["sire25"])

    def test_legacy_provider_alias_is_accepted(self):
        rows = [{"id": "legacy", "provider": "STRATO HiDrive", "enabled": True}]
        result = eligible_hidrive_accounts(Store(), lambda _store: rows)
        self.assertEqual([x["id"] for x in result], ["legacy"])

    def test_disabled_or_non_strato_accounts_are_not_offered(self):
        rows = [
            {"id": "disabled", "provider_code": "STRATO_HIDRIVE", "enabled": False},
            {"id": "other", "provider_code": "GENERIC_SFTP", "name": "Mein Server", "enabled": True, "methods": ["SFTP"]},
            {"id": "active", "provider_code": "STRATO_HIDRIVE", "enabled": True},
        ]
        store = Store({
            "filesystem_targets": [
                {"kind": "CLOUD-SFTP", "cloud_method": "SFTP", "cloud_account_id": "other"}
            ]
        })
        result = eligible_hidrive_accounts(store, lambda _store: rows)
        self.assertEqual([x["id"] for x in result], ["active"])

    def test_missing_enabled_flag_defaults_to_active_for_legacy_records(self):
        rows = [{"id": "legacy", "provider_code": "STRATO_HIDRIVE"}]
        result = eligible_hidrive_accounts(Store(), lambda _store: rows)
        self.assertEqual([x["id"] for x in result], ["legacy"])


if __name__ == "__main__":
    unittest.main()
