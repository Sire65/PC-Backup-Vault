import unittest
from unittest.mock import patch

from nas_recovery.network import NasNetworkDiagnostics, normalize_host


class NasNetworkTests(unittest.TestCase):
    def test_accepts_ipv4_and_hostname(self):
        self.assertEqual(normalize_host("192.168.1.20"), "192.168.1.20")
        self.assertEqual(normalize_host("nas.local"), "nas.local")

    def test_rejects_urls_and_spaces(self):
        with self.assertRaises(ValueError):
            normalize_host("http://nas.local")
        with self.assertRaises(ValueError):
            normalize_host("nas server")

    @patch("nas_recovery.network.socket.gethostbyname", return_value="192.168.1.20")
    @patch("nas_recovery.network.socket.create_connection")
    def test_basic_report_is_connectivity_only(self, create_connection, gethostbyname):
        class DummyConnection:
            def __enter__(self): return self
            def __exit__(self, *args): return False
        create_connection.return_value = DummyConnection()
        report = NasNetworkDiagnostics().basic_report("nas.local")
        self.assertEqual(report.resolved_ip, "192.168.1.20")
        self.assertEqual(len(report.ports), 4)
        self.assertTrue(all(item.open for item in report.ports))
        # Diagnostics only opens TCP connections. No shell/configuration command exists here.
        self.assertEqual(create_connection.call_count, 4)


if __name__ == "__main__":
    unittest.main()
