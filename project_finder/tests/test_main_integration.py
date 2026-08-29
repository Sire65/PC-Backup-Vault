import unittest

from project_finder.main_integration import enable_project_finder


class DummyApp:
    def _build(self):
        self.built = True


class MainIntegrationTests(unittest.TestCase):
    def test_enable_is_idempotent_and_keeps_original_build_reference(self):
        original = DummyApp._build
        cls = enable_project_finder(DummyApp)
        wrapped = cls._build
        self.assertTrue(cls._project_finder_enabled)
        self.assertTrue(callable(cls.open_project_finder))
        self.assertIsNot(wrapped, original)
        self.assertIs(enable_project_finder(cls)._build, wrapped)


if __name__ == '__main__':
    unittest.main()
