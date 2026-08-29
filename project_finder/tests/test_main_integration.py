import unittest

from project_finder.main_integration import enable_project_finder


class DummyApp:
    def _build(self):
        self.built = True

    def start_backup(self):
        return 'backup'

    def pause_backup(self):
        return 'pause'

    def b2_upload(self):
        return 'b2'

    def refresh_dashboard(self):
        return 'dashboard'

    def kc_communication(self):
        return 'kc'


class MainIntegrationTests(unittest.TestCase):
    def test_enable_is_idempotent_and_keeps_original_build_reference(self):
        original = DummyApp._build
        cls = enable_project_finder(DummyApp)
        wrapped = cls._build
        self.assertTrue(cls._project_finder_enabled)
        self.assertTrue(callable(cls.open_project_finder))
        self.assertIsNot(wrapped, original)
        self.assertIs(enable_project_finder(cls)._build, wrapped)

    def test_project_finder_does_not_replace_core_app_methods(self):
        class CoreApp:
            def _build(self):
                pass

            def start_backup(self):
                return 'backup'

            def pause_backup(self):
                return 'pause'

            def b2_upload(self):
                return 'b2'

            def refresh_dashboard(self):
                return 'dashboard'

            def kc_communication(self):
                return 'kc'

        protected = {
            name: getattr(CoreApp, name)
            for name in ('start_backup', 'pause_backup', 'b2_upload', 'refresh_dashboard', 'kc_communication')
        }
        enable_project_finder(CoreApp)
        for name, original in protected.items():
            self.assertIs(getattr(CoreApp, name), original, name)


if __name__ == '__main__':
    unittest.main()
