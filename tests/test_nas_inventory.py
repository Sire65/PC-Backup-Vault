import unittest

from nas_recovery.inventory import build_storage_inventory, parse_df_output, parse_mount_output


class NasInventoryTests(unittest.TestCase):
    def test_parses_mounts_and_read_only_flag(self):
        mounts = parse_mount_output("/dev/md2 on /shares/Public type ext4 (rw,noatime)\n/dev/sda1 on /boot type ext2 (ro,relatime)\n")
        self.assertEqual(len(mounts), 2)
        self.assertEqual(mounts[0].target, "/shares/Public")
        self.assertFalse(mounts[0].read_only)
        self.assertTrue(mounts[1].read_only)

    def test_parses_df_and_detects_data_mounts(self):
        df = "Filesystem Size Used Avail Use% Mounted on\n/dev/md2 3.6T 2.1T 1.5T 59% /shares/Public\n/dev/root 2.0G 1.0G 1.0G 50% /\n"
        entries = parse_df_output(df)
        self.assertEqual(entries[0].available, "1.5T")
        inventory = build_storage_inventory("/dev/md2 on /shares/Public type ext4 (rw,noatime)\n", df)
        self.assertEqual(inventory.likely_data_mounts, ("/shares/Public",))

    def test_parser_has_no_execution_side_effect(self):
        inventory = build_storage_inventory("", "")
        self.assertEqual(inventory.mounts, ())
        self.assertEqual(inventory.usage, ())
        self.assertEqual(inventory.likely_data_mounts, ())


if __name__ == "__main__":
    unittest.main()
