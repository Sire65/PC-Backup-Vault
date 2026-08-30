import tempfile
import unittest
from pathlib import Path

from kc_backup_contract import KCBackupJobReport, KCProgramIdentity
from kc_backup_security import MaximumSecurityPolicy, guard_restore, preflight_paths


class BackupCentralContractTests(unittest.TestCase):
    def test_professional_job_contract(self):
        report = KCBackupJobReport(
            identity=KCProgramIdentity("KC Verwaltung", "KC Verwaltung", "2.0"),
            job_type="PREFLIGHT",
            status="SUCCESS",
            security_level="MAXIMUM",
            verify_level="NONE",
            files_total=3,
            bytes_total=1234,
        ).as_dict()
        self.assertEqual(report["program_id"], "kc-verwaltung")
        self.assertEqual(report["job_type"], "PREFLIGHT")
        self.assertEqual(report["security_level"], "MAXIMUM")

    def test_preflight_fails_closed_when_target_or_recovery_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "data.txt"
            src.write_text("safe", encoding="utf-8")
            result = preflight_paths([src], target_ready=False, recovery_material_ready=False)
            self.assertFalse(result.ok)
            self.assertEqual(result.status, "BLOCKED")
            self.assertGreaterEqual(len(result.blockers), 2)

    def test_preflight_counts_readable_payload_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "source"
            src.mkdir()
            (src / "a.txt").write_bytes(b"abc")
            (src / "b.txt").write_bytes(b"12345")
            result = preflight_paths([src], target_ready=True, recovery_material_ready=True)
            self.assertTrue(result.ok)
            self.assertEqual(result.files, 2)
            self.assertEqual(result.bytes_total, 8)

    def test_restore_is_blocked_without_verified_source_and_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = guard_restore(
                source_verified=False,
                recovery_material_ready=True,
                target=Path(tmp) / "restore",
                explicit_confirmation=False,
            )
            self.assertFalse(result.allowed)
            self.assertGreaterEqual(len(result.blockers), 2)

    def test_restore_overwrite_is_blocked_in_maximum_security(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "restore"
            target.mkdir()
            result = guard_restore(
                source_verified=True,
                recovery_material_ready=True,
                target=target,
                overwrite_requested=True,
                explicit_confirmation=True,
                policy=MaximumSecurityPolicy(),
            )
            self.assertFalse(result.allowed)
            self.assertTrue(any("Ueberschreiben" in item for item in result.blockers))

    def test_restore_to_separate_empty_target_can_be_authorized(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "restore"
            result = guard_restore(
                source_verified=True,
                recovery_material_ready=True,
                target=target,
                explicit_confirmation=True,
                protected_roots=[Path(tmp) / "original"],
            )
            self.assertTrue(result.allowed)
            self.assertFalse(result.blockers)


if __name__ == "__main__":
    unittest.main()
