import tempfile
import unittest
from pathlib import Path

from cloud_failback import (
    DECIMAL_GB,
    conservative_planned_bytes,
    evaluate_capacity,
    safe_limit_bytes,
)


class CloudFailbackCostGuardTests(unittest.TestCase):
    def test_default_zero_cost_limit_keeps_half_gb_reserve(self):
        self.assertEqual(
            safe_limit_bytes({"free_limit_gb": 10, "hard_limit_gb": 10}),
            9_500_000_000,
        )

    def test_user_lower_hard_limit_is_respected(self):
        self.assertEqual(
            safe_limit_bytes({"free_limit_gb": 10, "hard_limit_gb": 7.25}),
            7_250_000_000,
        )

    def test_capacity_allows_only_when_backup_fits_safe_limit(self):
        decision = evaluate_capacity(
            "Backblaze B2",
            used_bytes=8 * DECIMAL_GB,
            planned_bytes=1 * DECIMAL_GB,
            config={"free_limit_gb": 10, "hard_limit_gb": 10},
        )
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.free_after_bytes, 500_000_000)

    def test_capacity_blocks_before_cost_threshold(self):
        decision = evaluate_capacity(
            "Backblaze B2",
            used_bytes=9 * DECIMAL_GB,
            planned_bytes=600_000_000,
            config={"free_limit_gb": 10, "hard_limit_gb": 10},
        )
        self.assertFalse(decision.allowed)
        self.assertLess(decision.free_after_bytes, 0)
        self.assertIn("blockiert", decision.reason.lower())

    def test_planned_size_is_conservative(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "payload.bin"
            source.write_bytes(b"x" * 1_000_000)
            planned = conservative_planned_bytes([source])
            self.assertGreater(planned, source.stat().st_size)
            self.assertEqual(planned, int(1_000_000 * 1.02) + 4096)


if __name__ == "__main__":
    unittest.main()
