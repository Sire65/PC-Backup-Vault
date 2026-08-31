import unittest
from unittest.mock import patch

from nas_recovery.ssh_legacy_probe import LegacySshProbe, classify_ssh_banner


class LegacySshProbeTests(unittest.TestCase):
    def test_old_openssh_is_classified_as_legacy(self):
        self.assertTrue(classify_ssh_banner("SSH-2.0-OpenSSH_5.1p1 Debian-5"))

    def test_modern_openssh_is_not_classified_as_legacy(self):
        self.assertFalse(classify_ssh_banner("SSH-2.0-OpenSSH_9.8"))

    @patch("nas_recovery.ssh_legacy_probe.runtime_supports_ssh_dss", return_value=False)
    @patch.object(LegacySshProbe, "read_banner", return_value="SSH-2.0-OpenSSH_5.1p1")
    def test_legacy_without_runtime_support_stays_blocked(self, _banner, _runtime):
        profile = LegacySshProbe().profile("nas.local")
        self.assertTrue(profile.looks_legacy)
        self.assertFalse(profile.dss_runtime_available)
        self.assertIn("bleibt gesperrt", profile.recommendation)

    @patch("nas_recovery.ssh_legacy_probe.runtime_supports_ssh_dss", return_value=False)
    @patch.object(LegacySshProbe, "read_banner", return_value="SSH-2.0-OpenSSH_9.8")
    def test_modern_banner_recommends_standard_read_only_ssh(self, _banner, _runtime):
        profile = LegacySshProbe().profile("nas.local")
        self.assertFalse(profile.looks_legacy)
        self.assertIn("Standard-Read-only-SSH", profile.recommendation)


if __name__ == "__main__":
    unittest.main()
