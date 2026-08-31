import unittest

from nas_recovery.missing_disk import MissingDiskDetector, StorageSnapshot


class MissingDiskDetectorTests(unittest.TestCase):
    def setUp(self):
        self.detector = MissingDiskDetector()

    def test_partition_without_drive_letter_is_reported(self):
        snapshot = StorageSnapshot(
            disks=({"Number": 2, "FriendlyName": "DataDisk", "PartitionStyle": "GPT", "IsOffline": False, "HealthStatus": "Healthy", "OperationalStatus": "Online"},),
            physical_disks=(),
            partitions=({"DiskNumber": 2, "PartitionNumber": 1, "DriveLetter": None, "Size": 1000},),
            volumes=(),
            pnp_disks=(),
        )
        findings = self.detector.evaluate(snapshot)
        self.assertTrue(any("kein Laufwerksbuchstabe" in f.title for f in findings))

    def test_offline_disk_is_critical(self):
        snapshot = StorageSnapshot(
            disks=({"Number": 1, "FriendlyName": "OldDisk", "PartitionStyle": "GPT", "IsOffline": True, "HealthStatus": "Healthy", "OperationalStatus": "Offline"},),
            physical_disks=(), partitions=(), volumes=(), pnp_disks=(),
        )
        findings = self.detector.evaluate(snapshot)
        self.assertTrue(any(f.severity == "red" and "offline" in f.title for f in findings))

    def test_unknown_partition_style_warns_not_to_initialize(self):
        snapshot = StorageSnapshot(
            disks=({"Number": 4, "FriendlyName": "Important", "PartitionStyle": "RAW", "IsOffline": False, "HealthStatus": "Healthy", "OperationalStatus": "Online"},),
            physical_disks=(), partitions=(), volumes=(), pnp_disks=(),
        )
        findings = self.detector.evaluate(snapshot)
        critical = [f for f in findings if f.severity == "red"]
        self.assertTrue(critical)
        self.assertTrue(any("nicht initialisieren" in f.detail.lower() or "keine initialisierung" in f.detail.lower() for f in critical))

    def test_pnp_visible_but_get_disk_empty_is_reported(self):
        snapshot = StorageSnapshot(
            disks=(), physical_disks=(), partitions=(), volumes=(),
            pnp_disks=({"FriendlyName": "USB Bridge", "Status": "OK", "Present": True},),
        )
        findings = self.detector.evaluate(snapshot)
        self.assertTrue(any("Hardware sichtbar" in f.title for f in findings))


if __name__ == "__main__":
    unittest.main()
