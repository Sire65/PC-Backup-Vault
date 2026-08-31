import unittest

from function_catalog import TASKS, task_for_id, visible_tasks


class FunctionCatalogTests(unittest.TestCase):
    def test_simple_mode_hides_advanced_technical_tasks(self):
        simple = visible_tasks(advanced=False)
        self.assertTrue(simple)
        self.assertTrue(all(not task.advanced for task in simple))
        self.assertLess(len(simple), len(TASKS))

    def test_core_user_jobs_have_clear_destinations(self):
        expected = {
            "secure": "backup",
            "check_disk": "disk",
            "recover": "nas",
            "restore": "restore",
            "projects": "finder",
            "system": "tuev",
        }
        for task_id, module_id in expected.items():
            task = task_for_id(task_id)
            self.assertIsNotNone(task)
            self.assertEqual(task.module_id, module_id)
            self.assertTrue(task.question)
            self.assertTrue(task.detail)

    def test_unknown_task_fails_closed(self):
        self.assertIsNone(task_for_id("does-not-exist"))


if __name__ == "__main__":
    unittest.main()
