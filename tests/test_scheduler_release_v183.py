from __future__ import annotations

import unittest
from unittest import mock

import scheduler


class SchedulerReleaseTests(unittest.TestCase):
    def test_manual_plan_is_healthy_without_windows_task(self):
        plan = {"id": "12345678-abcd", "name": "Manuell", "schedule_type": "MANUAL"}
        ok, msg = scheduler.task_status(plan)
        self.assertTrue(ok)
        self.assertIn("keine Windows-Aufgabe erforderlich", msg)
        result, detail = scheduler.task_diagnostic(plan)
        self.assertEqual(result, "PASS")
        self.assertIn("Manuell", detail)

    @mock.patch.object(scheduler, "_run")
    @mock.patch.object(scheduler.os, "name", "nt")
    def test_missing_scheduled_task_is_warning(self, run):
        run.return_value = mock.Mock(returncode=1, stdout="", stderr="FEHLER: Datei nicht gefunden")
        plan = {"id": "12345678-abcd", "name": "Täglich", "schedule_type": "DAILY", "schedule_time": "20:00"}
        result, detail = scheduler.task_diagnostic(plan)
        self.assertEqual(result, "WARN")
        self.assertIn("fehlt", detail)

    @mock.patch.object(scheduler, "install_task")
    @mock.patch.object(scheduler, "remove_task")
    def test_sync_repairs_only_auto_managed_plans(self, remove_task, install_task):
        install_task.return_value = (True, "OK")
        remove_task.return_value = (False, "nicht vorhanden")
        store = mock.Mock()
        store.data = {"plans": [
            {"id": "11111111-a", "name": "Manuell", "schedule_type": "MANUAL", "scheduler_auto_sync": True},
            {"id": "22222222-b", "name": "Auto", "schedule_type": "DAILY", "scheduler_auto_sync": True},
            {"id": "33333333-c", "name": "Extern", "schedule_type": "DAILY", "scheduler_auto_sync": False},
        ]}
        results = scheduler.sync_all_tasks(store)
        remove_task.assert_called_once()
        install_task.assert_called_once()
        self.assertEqual(results[0][1], "PASS")
        self.assertEqual(results[1][1], "PASS")
        self.assertEqual(results[2][1], "SKIP")


if __name__ == "__main__":
    unittest.main()
