import unittest

from hidrive_live_runtime_fix_v1927 import resolve_hidrive_runtime_accounts


class Store:
    def __init__(self, data=None):
        self.data = data or {}


class HiDriveLiveRuntimeFixTests(unittest.TestCase):
    def test_exact_tuev_shape_resolves_both_accounts_without_metadata_hints(self):
        store = Store()
        accounts = [
            {"id": "hausmeister-id", "name": "Cloud Konto A", "username": "hausmeister1", "enabled": True},
            {"id": "sire25-id", "name": "Cloud Konto B", "username": "sire25", "enabled": True},
        ]
        targets = [
            {
                "id": "cloud-hausmeister-id",
                "name": "Cloud · Strato_hausmeister1",
                "kind": "CLOUD-SFTP",
                "cloud_method": "SFTP",
                "cloud_account_id": "hausmeister-id",
                "path": "/users/hausmeister1/PC_Backup_Vault",
            },
            {
                "id": "cloud-sire25-id",
                "name": "Cloud · Strato_sire25",
                "kind": "CLOUD-SFTP",
                "cloud_method": "SFTP",
                "cloud_account_id": "sire25-id",
                "path": "/users/sire25/PC_Backup_Vault",
            },
        ]
        result, diag = resolve_hidrive_runtime_accounts(
            store, lambda _store: targets, lambda _store: accounts
        )
        self.assertEqual([x["id"] for x in result], ["hausmeister-id", "sire25-id"])
        self.assertEqual(diag["sftp_targets"], 2)
        self.assertEqual(diag["matched_accounts"], 2)
        self.assertEqual(diag["missing_account_ids"], ())

    def test_uses_runtime_targets_function_not_raw_store_key(self):
        store = Store({"filesystem_targets": []})
        accounts = [{"id": "live-id", "name": "Beliebiger Name", "enabled": True}]
        runtime_targets = [{
            "kind": "CLOUD-SFTP",
            "cloud_method": "SFTP",
            "cloud_account_id": "live-id",
        }]
        result, diag = resolve_hidrive_runtime_accounts(
            store, lambda _store: runtime_targets, lambda _store: accounts
        )
        self.assertEqual([x["id"] for x in result], ["live-id"])
        self.assertEqual(diag["filesystem_targets"], 1)

    def test_missing_target_account_is_reported_in_diagnostics(self):
        store = Store()
        targets = [{
            "kind": "CLOUD-SFTP",
            "cloud_method": "SFTP",
            "cloud_account_id": "missing-id",
        }]
        result, diag = resolve_hidrive_runtime_accounts(
            store, lambda _store: targets, lambda _store: []
        )
        self.assertEqual(result, [])
        self.assertEqual(diag["missing_account_ids"], ("missing-id",))
        self.assertEqual(diag["sftp_targets"], 1)

    def test_disabled_account_stays_excluded_even_when_target_exists(self):
        store = Store()
        accounts = [{"id": "off", "name": "Strato_alt", "enabled": False}]
        targets = [{
            "kind": "CLOUD-SFTP",
            "cloud_method": "SFTP",
            "cloud_account_id": "off",
        }]
        result, diag = resolve_hidrive_runtime_accounts(
            store, lambda _store: targets, lambda _store: accounts
        )
        self.assertEqual(result, [])
        self.assertEqual(diag["matched_accounts"], 0)

    def test_strato_account_is_available_before_bridge_exists(self):
        store = Store()
        accounts = [{
            "id": "new",
            "provider_code": "STRATO_HIDRIVE",
            "name": "Neues HiDrive",
            "username": "user",
            "enabled": True,
        }]
        result, diag = resolve_hidrive_runtime_accounts(
            store, lambda _store: [], lambda _store: accounts
        )
        self.assertEqual([x["id"] for x in result], ["new"])
        self.assertEqual(diag["sftp_targets"], 0)


if __name__ == "__main__":
    unittest.main()
