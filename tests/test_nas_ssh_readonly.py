import unittest

from nas_recovery.ssh_readonly import READ_ONLY_COMMANDS, UnsafeSshCommand, validate_read_only_command


class SshReadOnlySafetyTests(unittest.TestCase):
    def test_all_declared_commands_are_whitelisted(self):
        for _title, command in READ_ONLY_COMMANDS:
            self.assertEqual(validate_read_only_command(command), command)

    def test_mutating_commands_are_rejected(self):
        dangerous = [
            "rm -rf /",
            "touch /tmp/test",
            "mount -o remount,rw /",
            "mdadm --assemble --force /dev/md0",
            "fsck -y /dev/sda1",
            "reboot",
            "shutdown -h now",
            "echo x > /etc/test",
        ]
        for command in dangerous:
            with self.subTest(command=command):
                with self.assertRaises(UnsafeSshCommand):
                    validate_read_only_command(command)

    def test_shell_chaining_is_rejected(self):
        for command in ["uname -a; reboot", "df -h && touch /tmp/x", "mount | tee /tmp/x"]:
            with self.subTest(command=command):
                with self.assertRaises(UnsafeSshCommand):
                    validate_read_only_command(command)


if __name__ == "__main__":
    unittest.main()
