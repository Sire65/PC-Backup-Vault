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

    def test_linked_cloud_sftp_target_is_authoritative_without_strato_hints(self):
        rows = [
            {
                "id": "sire25",
                "name": "Cloud Konto A",
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

    def test_unlinked_non_strato_account_is_not_offered(self):
        rows = [
            {"id": "other", "provider_code": "GENERIC_SFTP", "name": "Mein Server", "enabled": True, "methods": ["SFTP"]},
            {"id": "active", "provider_code": "STRATO_HIDRIVE", "enabled": True},
        ]
        result = eligible_hidrive_accounts(Store(), lambda _store: rows)
        self.assertEqual([x["id"] for x in result], ["active"])

    def test_disabled_linked_account_is_offered_because_runtime_target_is_authoritative(self):
        rows = [{"id": "disabled", "name": "Cloud Konto", "enabled": False}]
        store = Store({
            "filesystem_targets": [
                {"kind": "CLOUD-SFTP", "cloud_method": "SFTP", "cloud_account_id": "disabled"}
            ]
        })
        result = eligible_hidrive_accounts(store, lambda _store: rows)
        self.assertEqual([x["id"] for x in result], ["disabled"])

    def test_disabled_unlinked_account_stays_excluded(self):
        rows = [{
            "id": "disabled",
            "name": "Strato_alt",
            "provider_code": "STRATO_HIDRIVE",
            "enabled": False,
        }]
        result = eligible_hidrive_accounts(Store(), lambda _store: rows)
        self.assertEqual(result, [])

    def test_missing_enabled_flag_defaults_to_active_for_legacy_records(self):
        rows = [{"id": "legacy", "provider_code": "STRATO_HIDRIVE"}]
        result = eligible_hidrive_accounts(Store(), lambda _store: rows)
        self.assertEqual([x["id"] for x in result], ["legacy"])


if __name__ == "__main__":
    unittest.main()
