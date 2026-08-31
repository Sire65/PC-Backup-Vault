import tempfile
import unittest
from pathlib import Path

from nas_recovery.safety import RecoverySafetyPolicy, UnsafeRecoveryOperation
from nas_recovery.service import NasRecoveryService, PhysicalDisk


class RecoverySafetyPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = RecoverySafetyPolicy()

    def test_physical_drive_detection(self):
        self.assertTrue(self.policy.is_physical_drive(r"\\.\PhysicalDrive3"))
        self.assertFalse(self.policy.is_physical_drive(r"D:\images\disk3.img"))

    def test_write_to_original_physical_drive_is_blocked(self):
        with self.assertRaises(UnsafeRecoveryOperation):
            self.policy.assert_original_disk_read_only(r"\\.\PhysicalDrive0", write=True)

    def test_dangerous_commands_are_blocked(self):
        samples = [
            "diskpart clean",
            "chkdsk /f E:",
            "mdadm --assemble --force /dev/md0",
            "mount -o rw /dev/sda1 /mnt/x",
            "Set-Disk -IsReadOnly $false -Number 2",
        ]
        for command in samples:
            with self.subTest(command=command):
                with self.assertRaises(UnsafeRecoveryOperation):
                    self.policy.assert_command_safe(command)

    def test_read_only_powershell_query_is_allowed(self):
        self.policy.assert_command_safe("Get-Disk | Select Number,FriendlyName")

    def test_image_destination_must_not_be_physical_drive(self):
        with self.assertRaises(UnsafeRecoveryOperation):
            self.policy.assert_image_destination(
                r"\\.\PhysicalDrive1", r"\\.\PhysicalDrive2"
            )


class RecoveryServiceTests(unittest.TestCase):
    def test_disk_device_path_is_explicit(self):
        disk = PhysicalDisk(4, "X", "S", "USB", 100, "Online", "GPT", False, True)
        self.assertEqual(disk.device_path, r"\\.\PhysicalDrive4")

    def test_sha256_file(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "sample.bin"
            path.write_bytes(b"abc")
            self.assertEqual(
                NasRecoveryService.sha256_file(path),
                "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
            )


if __name__ == "__main__":
    unittest.main()
