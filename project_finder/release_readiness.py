from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Mapping

from .integration_gate import PASS, BLOCKED, NOT_CHECKED, merge_gate_from_evidence


@dataclass(frozen=True)
class ReadinessInput:
    local_source_verified: bool = False
    local_git_compared: bool = False
    backup_start_passed: bool = False
    backup_pause_passed: bool = False
    b2_passed: bool = False
    dashboard_passed: bool = False
    communication_passed: bool = False
    runner_passed: bool = False
    quarantine_passed: bool = False
    project_finder_passed: bool = False


def _state(value: bool) -> str:
    return PASS if value else NOT_CHECKED


def build_release_readiness(inp: ReadinessInput, evidence: Mapping[str, str] | None = None) -> dict:
    """Build release readiness only from explicit measured checks.

    Unknown checks stay NOT_CHECKED. No inference from branch names, version labels,
    preview builds or chat claims is permitted.
    """
    proof = dict(evidence or {})
    flags = {
        "SOURCE": inp.local_source_verified,
        "LOCAL_GIT": inp.local_git_compared,
        "BACKUP_START": inp.backup_start_passed,
        "BACKUP_PAUSE": inp.backup_pause_passed,
        "B2": inp.b2_passed,
        "DASHBOARD": inp.dashboard_passed,
        "COMMUNICATION": inp.communication_passed,
        "RUNNER": inp.runner_passed,
        "QUARANTINE": inp.quarantine_passed,
        "PROJECT_FINDER": inp.project_finder_passed,
    }
    gate_evidence = {
        cid: (_state(ok), proof.get(cid, "") if ok else "")
        for cid, ok in flags.items()
    }
    gate = merge_gate_from_evidence(gate_evidence)
    complete = gate["state"] == "READY_FOR_MERGE_REVIEW"
    return {
        "schema": "pc-backup-vault.release-readiness.v1",
        "input": asdict(inp),
        "gate": gate,
        "release_state": "READY_FOR_RELEASE_REVIEW" if complete else "RELEASE_BLOCKED",
        "release_ready": False,
        "release_review_candidate": complete,
        "automatic_release": False,
        "rule": "Eine produktive Version wird erst nach lokalem Quellstand-Abgleich und allen belegten Kern-/Project-Finder-Prüfungen zur Release-Prüfung zugelassen.",
    }
