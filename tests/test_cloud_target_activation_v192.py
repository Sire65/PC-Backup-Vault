import unittest

from cloud_target_activation_v192 import _activate_account_target, target_state
from storage_v180 import DISPLAY


class Store:
    def __init__(self, data):
        self.data = data
        self.saved = 0
    def save(self):
        self.saved += 1


class Var:
    def __init__(self):
        self.value = None
    def set(self, value):
        self.value = value


class App:
    def __init__(self):
        self.payload_var = Var()
        self.updated = 0
    def update_backup_recommendation(self):
        self.updated += 1


class Settings:
    def __init__(self, app):
        self.app = app


class Tab:
    pass


class CloudTargetActivationTests(unittest.TestCase):
    def test_target_state_distinguishes_prepared_and_active(self):
        store = Store({
            "filesystem_targets": [
                {"id": "cloud-a", "cloud_account_id": "a", "name": "HiDrive A"},
                {"id": "cloud-b", "cloud_account_id": "b", "name": "HiDrive B"},
            ],
            "active_filesystem_target_id": "cloud-b",
        })
        self.assertEqual(target_state(store, "a")["prepared"], True)
        self.assertEqual(target_state(store, "a")["active"], False)
        self.assertEqual(target_state(store, "b")["active"], True)

    def test_activate_account_target_switches_real_manual_backup_destination(self):
        store = Store({
            "filesystem_targets": [
                {"id": "cloud-a", "cloud_account_id": "a", "name": "Cloud · sire25", "cloud_method": "SFTP"},
            ],
            "active_filesystem_target_id": None,
            "payload_target_default": "B2",
        })
        app = App()
        tab = Tab(); tab.store = store; tab.current_id = "a"; tab.settings = Settings(app)
        state = _activate_account_target(tab)
        self.assertTrue(state["active"])
        self.assertEqual(store.data["active_filesystem_target_id"], "cloud-a")
        self.assertEqual(store.data["payload_target_default"], "FILESYSTEM")
        self.assertEqual(app.payload_var.value, DISPLAY)
        self.assertGreaterEqual(store.saved, 1)

    def test_missing_bridge_does_not_change_destination(self):
        store = Store({"filesystem_targets": [], "active_filesystem_target_id": "old", "payload_target_default": "B2"})
        app = App()
        tab = Tab(); tab.store = store; tab.current_id = "missing"; tab.settings = Settings(app)
        state = _activate_account_target(tab)
        self.assertFalse(state["prepared"])
        self.assertEqual(store.data["active_filesystem_target_id"], "old")
        self.assertEqual(store.data["payload_target_default"], "B2")
        self.assertIsNone(app.payload_var.value)


if __name__ == "__main__":
    unittest.main()
