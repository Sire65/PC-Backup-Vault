import unittest

from main_navigation_v1919 import classify_action_text


class MainNavigationTests(unittest.TestCase):
    def test_restore_actions_are_grouped(self):
        for text in ("♻ Wiederherstellen","☁ Backup-Explorer","📊 Dashboard","Letzter Report","Historie","🖥 Windows-Systemabbild"):
            self.assertEqual(classify_action_text(text,"overview"),"restore")

    def test_storage_actions_are_grouped(self):
        self.assertEqual(classify_action_text("☁ HiDrive Live","backup"),"storage")
        self.assertEqual(classify_action_text("🗂 Speicher-Explorer","backup"),"storage")

    def test_system_project_actions_are_grouped(self):
        for text in ("TÜV / Core prüfen","ADMIN","KC Kommunikation","🔎 Inventur / Project Finder"):
            self.assertEqual(classify_action_text(text,"backup"),"system")

    def test_unknown_overview_action_stays_in_restore_group(self):
        self.assertEqual(classify_action_text("Zusatzfunktion","overview"),"restore")


if __name__ == "__main__":
    unittest.main()
