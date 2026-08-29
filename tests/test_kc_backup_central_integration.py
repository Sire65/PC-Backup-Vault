import unittest

from kc_backup_central_integration import enable_backup_central


class DummyApp:
    def _build(self):
        self.built = True


class BackupCentralIntegrationTests(unittest.TestCase):
    def test_enable_is_idempotent_and_replaces_one_touch_entrypoint(self):
        enable_backup_central(DummyApp)
        first_build = DummyApp._build
        first_one_touch = DummyApp.run_default_one_touch
        enable_backup_central(DummyApp)
        self.assertIs(DummyApp._build, first_build)
        self.assertIs(DummyApp.run_default_one_touch, first_one_touch)
        self.assertTrue(DummyApp._kc_backup_central_enabled)
        self.assertTrue(callable(DummyApp.open_backup_calendar))


if __name__ == "__main__":
    unittest.main()
