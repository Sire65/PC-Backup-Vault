from __future__ import annotations
import unittest
from unittest.mock import patch
import kicc_backup_telemetry as telemetry

class BackupTelemetryByteMappingTests(unittest.TestCase):
    def test_original_bytes_are_reported_not_stored_bytes(self):
        job = (
            "job-1", "2026-09-18T07:00:00+00:00", "2026-09-18T07:05:00+00:00",
            "SUCCESS", 12, 123456, 65432, 0, "", "manual", "Test",
            "INCREMENTAL", 12, 12, 0, "B2"
        )
        with patch.object(telemetry, "recent_jobs", return_value=[job]), \
             patch.object(telemetry, "recent_verifications", return_value=[]), \
             patch.object(telemetry, "recent_restore_tests", return_value=[]):
            out = telemetry._latest_snapshot("unused")
        self.assertEqual(out["lastBackupBytes"], 123456)
        self.assertNotEqual(out["lastBackupBytes"], 65432)

if __name__ == "__main__":
    unittest.main()
