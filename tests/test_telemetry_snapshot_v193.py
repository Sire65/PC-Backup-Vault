import unittest

from telemetry_snapshot_v193 import build_snapshot, system_check_view


class TelemetrySnapshotV193Tests(unittest.TestCase):
    def test_snapshot_redacts_sensitive_keys_recursively(self):
        snapshot = build_snapshot(
            app_version="1.9.3",
            vault_status="ok",
            last_job={
                "status": "SUCCESS",
                "password": "must-not-leak",
                "nested": {"recovery_key": "must-not-leak", "files": 3},
            },
            targets=[
                {
                    "id": "hidrive_1",
                    "status": "healthy",
                    "token": "must-not-leak",
                    "endpoint": "sftp.hidrive.strato.com:22",
                }
            ],
        )

        text = repr(snapshot)
        self.assertNotIn("must-not-leak", text)
        self.assertEqual(snapshot["lastJob"]["nested"]["files"], 3)
        self.assertEqual(snapshot["targets"][0]["endpoint"], "sftp.hidrive.strato.com:22")

    def test_snapshot_normalises_statuses(self):
        self.assertEqual(build_snapshot(app_version="x", vault_status="ok")["status"], "healthy")
        self.assertEqual(build_snapshot(app_version="x", vault_status="error")["status"], "critical")
        self.assertEqual(build_snapshot(app_version="x", vault_status="unexpected")["status"], "unknown")

    def test_system_check_view_uses_common_shape_and_escalates_target_failure(self):
        snapshot = build_snapshot(
            app_version="1.9.3",
            vault_status="healthy",
            targets=[
                {"id": "nas_backup", "status": "healthy"},
                {"id": "hidrive_1", "status": "critical"},
            ],
            last_verify={"status": "healthy"},
            last_restore_test={"status": "healthy"},
            capacity={"usage": 42, "label": "42 %"},
            generated_at="2026-09-07T20:00:00Z",
        )

        result = system_check_view(snapshot)
        self.assertEqual(result["id"], "backup_vault")
        self.assertEqual(result["status"], "critical")
        self.assertEqual(result["health"], "critical")
        self.assertEqual(result["usage"], 42)
        self.assertEqual(result["capacityLabel"], "42 %")
        self.assertEqual(result["metrics"]["generatedAt"], "2026-09-07T20:00:00Z")


if __name__ == "__main__":
    unittest.main()
