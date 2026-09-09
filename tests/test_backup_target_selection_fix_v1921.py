import unittest

from backup_target_selection_fix_v1921 import choose_effective_media


class BackupTargetSelectionFixTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            {"id": "cloud:haus", "name": "Strato_hausmeister1", "enabled": False},
            {"id": "cloud:sire", "name": "Strato_sire25", "enabled": True},
        ]

    def test_enabled_selected_row_wins(self):
        self.assertEqual(choose_effective_media(self.rows, "cloud:sire")["id"], "cloud:sire")

    def test_disabled_selected_row_falls_back_to_only_enabled_medium(self):
        self.assertEqual(choose_effective_media(self.rows, "cloud:haus")["id"], "cloud:sire")

    def test_no_selection_falls_back_to_only_enabled_medium(self):
        self.assertEqual(choose_effective_media(self.rows, None)["id"], "cloud:sire")

    def test_multiple_enabled_media_are_not_guessed(self):
        rows = list(self.rows) + [{"id": "b2", "name": "B2", "enabled": True}]
        self.assertIsNone(choose_effective_media(rows, "cloud:haus"))

    def test_explicit_enabled_selection_still_wins_with_multiple_enabled(self):
        rows = list(self.rows) + [{"id": "b2", "name": "B2", "enabled": True}]
        self.assertEqual(choose_effective_media(rows, "b2")["id"], "b2")


if __name__ == "__main__":
    unittest.main()
