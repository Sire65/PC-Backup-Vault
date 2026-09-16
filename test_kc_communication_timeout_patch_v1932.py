from __future__ import annotations

import unittest
from unittest.mock import patch

import kc_communication as kc
import kc_communication_timeout_patch as fix


class _Response:
    status = 200
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self, _limit): return b'{"ok":true}'


class KCTimeoutPatchTests(unittest.TestCase):
    def setUp(self):
        fix.apply_kc_communication_timeout_patch()
        self.client = kc.KCCommunicationClient("https://example.invalid", "device", "token", timeout=8)

    def _captured_timeout(self, payload):
        seen = {}
        def fake_urlopen(_req, timeout):
            seen["timeout"] = timeout
            return _Response()
        with patch.object(fix.urllib.request, "urlopen", fake_urlopen):
            self.client._post(payload)
        return seen["timeout"]

    def test_status_keeps_short_timeout(self):
        self.assertEqual(self._captured_timeout({"action":"status"}), 8)

    def test_emit_gets_separate_budget_below_ui_deadline(self):
        self.assertEqual(self._captured_timeout({"action":"emit"}), 12)
        self.assertLess(fix.EMIT_TIMEOUT_SECONDS, 15)

    def test_timeout_wording_does_not_claim_provider_failure(self):
        def fail(_req, timeout):
            raise TimeoutError("timed out")
        with patch.object(fix.urllib.request, "urlopen", fail):
            with self.assertRaises(kc.KCCommunicationError) as ctx:
                self.client._post({"action":"emit"})
        text = str(ctx.exception)
        self.assertIn("Versandstatus unbekannt", text)
        self.assertNotIn("Versand fehlgeschlagen", text)


if __name__ == "__main__":
    unittest.main()
