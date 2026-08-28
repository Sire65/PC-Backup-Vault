from __future__ import annotations

from dataclasses import asdict
from typing import Iterable

from .integration_report import compare_scan_candidates
from .scanner import ScanItem


def build_source_candidate_rows(items: Iterable[ScanItem]) -> list[dict]:
    """Build read-only source candidate rows from an existing disk scan."""
    rows = []
    for result in compare_scan_candidates(items):
        row = asdict(result)
        row["required_total"] = result.required_found + len(result.required_missing)
        row["required_summary"] = f"{result.required_found}/{row['required_total']}"
        row["risk"] = _risk(result.state)
        rows.append(row)
    return rows


def _risk(state: str) -> str:
    return {
        "DIVERGED": "RED",
        "VERSION_DIFFERS": "RED",
        "COMPARE_REQUIRED": "YELLOW",
        "MATCH_REFERENCE": "YELLOW",
        "INCOMPLETE": "GRAY",
    }.get(state, "YELLOW")
