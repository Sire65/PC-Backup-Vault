from __future__ import annotations

from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Iterable

from .full_tree_compare import as_report as full_tree_as_report, compare_full_tree
from .local_baseline_compare import LocalBaselineResult, compare_local_root, summarize_candidates
from .scanner import ScanItem
from .source_baseline import PC_BACKUP_VAULT_173

_REQUIRED = frozenset(PC_BACKUP_VAULT_173.required_files)


def candidate_roots_from_scan(items: Iterable[ScanItem]) -> list[str]:
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
    reference_manifest: dict[str, str] | None = None,
    test_state: str = "NOT_CHECKED",
) -> dict:
    """Build a conservative source-recovery report from measured evidence only.

    A caller cannot assert full-tree equality with a boolean. Full-tree verification is
    derived here by hashing a candidate against the supplied authoritative path/hash
    manifest. Required-file equality and total file count remain insufficient proof.
    """
    rows = list(items)
    candidates = compare_scan_candidates(rows, baseline_hashes=baseline_hashes)
    comparison = summarize_candidates(candidates)
    state_counts = Counter(x.state for x in candidates)
    duplicate_count = sum(1 for x in rows if x.duplicate_of)
    relevant_count = sum(1 for x in rows if x.score >= 40 or x.duplicate_of)

    full_tree_results = []
    if reference_manifest:
        for candidate in candidates:
            if candidate.state == "MATCH_REFERENCE":
                full_tree_results.append(compare_full_tree(candidate.root, reference_manifest))
    exact_matches = [x for x in full_tree_results if x.full_tree_verified]
    full_tree_verified = len(exact_matches) == 1 and len(full_tree_results) == 1

    if not candidates:
        recovery_state = "NO_SOURCE_CANDIDATE"
    elif state_counts.get("DIVERGED") or state_counts.get("VERSION_DIFFERS"):
        recovery_state = "LOCAL_REVIEW_REQUIRED"
    elif state_counts.get("COMPARE_REQUIRED"):
        recovery_state = "CONTENT_COMPARE_REQUIRED"
    elif state_counts.get("MATCH_REFERENCE") and not reference_manifest:
        recovery_state = "FULL_TREE_COMPARE_REQUIRED"
    elif state_counts.get("MATCH_REFERENCE") and not full_tree_verified:
        recovery_state = "FULL_TREE_MISMATCH"
    elif state_counts.get("MATCH_REFERENCE") and test_state == "PASS" and full_tree_verified:
        recovery_state = "REFERENCE_MATCH_VERIFIED"
    else:
        recovery_state = "TEST_REQUIRED"

    merge_review_candidate = recovery_state == "REFERENCE_MATCH_VERIFIED" and test_state == "PASS" and full_tree_verified
    return {
        "schema": "pc-backup-vault.integration-report.v3",
        "reference": {
            "version": PC_BACKUP_VAULT_173.version,
            "commit": PC_BACKUP_VAULT_173.commit_sha,
            "expected_file_count": PC_BACKUP_VAULT_173.expected_file_count,
            "manifest_file_count": len(reference_manifest or {}),
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
        "full_tree_verified": full_tree_verified,
        "full_tree_results": [full_tree_as_report(x) for x in full_tree_results],
        "recovery_state": recovery_state,
        "merge_review_candidate": merge_review_candidate,
        "merge_ready": False,
        "safety": {
            "read_only_analysis": True,
            "automatic_cleanup": False,
            "automatic_merge": False,
            "integration_gate_required": True,
            "caller_asserted_full_tree_proof_allowed": False,
            "local_newer_or_diverged_protected": True,
        },
        "next_action": _next_action(recovery_state),
    }


def _next_action(state: str) -> str:
    return {
        "NO_SOURCE_CANDIDATE": "Weitere Laufwerke/Ordner scannen; kein vollständiger Quellkandidat erkannt.",
        "LOCAL_REVIEW_REQUIRED": "Abweichende/lokal andere Kandidaten schützen und vollständig gegen Git vergleichen.",
        "CONTENT_COMPARE_REQUIRED": "Per-Datei-Hashes der Referenz laden und vollständigen Inhaltsvergleich durchführen.",
        "FULL_TREE_COMPARE_REQUIRED": "Vollständiges Referenzmanifest laden und alle Pfade/Dateiinhalte vergleichen.",
        "FULL_TREE_MISMATCH": "Vollbaum-Abweichungen prüfen; lokalen Stand schützen und keinesfalls automatisch überschreiben.",
        "TEST_REQUIRED": "Kandidat strukturell prüfen und vollständige Regression ausführen.",
        "REFERENCE_MATCH_VERIFIED": "An separaten Integrations-/TÜV-Gate übergeben; kein automatischer Merge oder Release.",
    }.get(state, "Manuelle Prüfung erforderlich.")
