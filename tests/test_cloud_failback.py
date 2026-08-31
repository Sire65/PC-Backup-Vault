from pathlib import Path

from cloud_failback import (
    DECIMAL_GB,
    conservative_planned_bytes,
    evaluate_capacity,
    safe_limit_bytes,
)


def test_default_zero_cost_limit_keeps_half_gb_reserve():
    assert safe_limit_bytes({"free_limit_gb": 10, "hard_limit_gb": 10}) == 9_500_000_000


def test_user_lower_hard_limit_is_respected():
    assert safe_limit_bytes({"free_limit_gb": 10, "hard_limit_gb": 7.25}) == 7_250_000_000


def test_capacity_allows_only_when_backup_fits_safe_limit():
    decision = evaluate_capacity(
        "Backblaze B2",
        used_bytes=8 * DECIMAL_GB,
        planned_bytes=1 * DECIMAL_GB,
        config={"free_limit_gb": 10, "hard_limit_gb": 10},
    )
    assert decision.allowed is True
    assert decision.free_after_bytes == 500_000_000


def test_capacity_blocks_before_cost_threshold():
    decision = evaluate_capacity(
        "Backblaze B2",
        used_bytes=9 * DECIMAL_GB,
        planned_bytes=600_000_000,
        config={"free_limit_gb": 10, "hard_limit_gb": 10},
    )
    assert decision.allowed is False
    assert decision.free_after_bytes < 0
    assert "blockiert" in decision.reason.lower()


def test_planned_size_is_conservative(tmp_path: Path):
    source = tmp_path / "payload.bin"
    source.write_bytes(b"x" * 1_000_000)
    planned = conservative_planned_bytes([source])
    assert planned > source.stat().st_size
    assert planned == int(1_000_000 * 1.02) + 4096
