from __future__ import annotations

from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Iterable

from .local_baseline_compare import LocalBaselineResult, compare_local_root, summarize_candidates
from .scanner import ScanItem
from .source_baseline import PC_BACKUP_VAULT_173


_REQUIRED = frozenset(PC_BACKUP_VAULT_173.required_files)


def candidate_roots_from_scan(items: Iterable[ScanItem]) -> list[str]:
    """Derive plausible PC Backup Vault source roots from an existing read-only scan.

    A directory is only a candidate when at least three distinct reference files are
    present. This avoids treating a single copied app.py or README-like file as a
    source tree. No filesystem mutation is performed.
    """
    hits: dict[str, set[str]] = {}
    for item in items:
        if item.name not in _REQUIRED:
            continue
        parent = str(Path(item.path).parent)
        hits.setdefault(parent, set()).add(item.name)
    return sorted(root for root, names in hits.items() if len(names) >= 3)


def compare_scan_candidates(items: Iterable[ScanItem], *, baseline_hashes: dict[str, str] | None = None) -> list[LocalBaselineResult]:
    rows = list(items)
    return [compare_local_root(root, baseline_hashes=baseline_hashes) for root in candidate_roots_from_scan(rows)]


def build_integration_report(
    items: Iterable[ScanItem],
    *,
    baseline_hashes: dict[str, str] | None = None,
    test_state: str = "NOT_CHECKED",
) -> dict:
    rows = list(items)
    candidates = compare_scan_candidates(rows, baseline_hashes=baseline_hashes)
    comparison = summarize_candidates(candidates)
    state_counts = Counter(x.state for x in candidates)
    duplicate_count = sum(1 for x in rows if x.duplicate_of)
    relevant_count = sum(1 for x in rows if x.score >= 40 or x.duplicate_of)

    if not candidates:
        recovery_state = "NO_SOURCE_CANDIDATE"
    elif state_counts.get("DIVERGED") or state_counts.get("VERSION_DIFFERS"):
        recovery_state = "LOCAL_REVIEW_REQUIRED"
    elif state_counts.get("COMPARE_REQUIRED"):
        recovery_state = "CONTENT_COMPARE_REQUIRED"
    elif state_counts.get("MATCH_REFERENCE") and test_state == "PASS":
        recovery_state = "REFERENCE_MATCH_VERIFIED"
    else:
        recovery_state = "TEST_REQUIRED"

    merge_ready = recovery_state == "REFERENCE_MATCH_VERIFIED" and test_state == "PASS"
    return {
        "schema": "pc-backup-vault.integration-report.v1",
        "reference": {
            "version": PC_BACKUP_VAULT_173.version,
            "commit": PC_BACKUP_VAULT_173.commit_sha,
            "expected_file_count": PC_BACKUP_VAULT_173.expected_file_count,
        },
        "scan": {
            "file_count": len(rows),
            "relevant_count": relevant_count,
            "duplicate_count": duplicate_count,
            "candidate_root_count": len(candidates),
        },
        "candidate_state_counts": dict(sorted(state_counts.items())),
        "candidates": [asdict(x) for x in candidates],
        "comparison": comparison,
        "test_state": test_state,
        "recovery_state": recovery_state,
        "merge_ready": merge_ready,
        "safety": {
            "read_only_analysis": True,
            "automatic_cleanup": False,
            "automatic_merge": False,
            "local_newer_or_diverged_protected": True,
        },
        "next_action": _next_action(recovery_state),
    }


def _next_action(state: str) -> str:
    return {
        "NO_SOURCE_CANDIDATE": "Weitere Laufwerke/Ordner scannen; kein vollständiger Quellkandidat erkannt.",
        "LOCAL_REVIEW_REQUIRED": "Abweichende/lokal andere Kandidaten schützen und vollständig gegen Git vergleichen.",
        "CONTENT_COMPARE_REQUIRED": "Per-Datei-Hashes der Referenz laden und vollständigen Inhaltsvergleich durchführen.",
        "TEST_REQUIRED": "Kandidat strukturell prüfen und vollständige Regression ausführen.",
        "REFERENCE_MATCH_VERIFIED": "Nur Merge-Prüfung freigeben; kein automatischer Merge oder Release.",
    }.get(state, "Manuelle Prüfung erforderlich.")
