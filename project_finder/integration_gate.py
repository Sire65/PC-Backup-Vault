from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable


PASS = "PASS"
BLOCKED = "BLOCKED"
NOT_CHECKED = "NOT_CHECKED"


@dataclass
class IntegrationCheck:
    check_id: str
    title: str
    state: str = NOT_CHECKED
    evidence: str = ""
    required: bool = True


REQUIRED_CHECKS = (
    ("SOURCE", "Führenden lokalen PC-Backup-Vault-GUI-Quellstand eindeutig bestimmt"),
    ("LOCAL_GIT", "Lokalen führenden Stand gegen Git verglichen"),
    ("BACKUP_START", "Backup Start regressionsgeprüft"),
    ("BACKUP_PAUSE", "Backup Pause/Fortsetzen regressionsgeprüft"),
    ("B2", "B2-Backupverhalten unverändert regressionsgeprüft"),
    ("DASHBOARD", "Dashboard/TÜV regressionsgeprüft"),
    ("COMMUNICATION", "KC-Communication-Anbindung regressionsgeprüft"),
    ("RUNNER", "Windows-Build des dedizierten Project-Finder-Runners geprüft"),
    ("QUARANTINE", "Quarantäne/Restore/Purge E2E geprüft"),
    ("PROJECT_FINDER", "Project-Finder Regression grün"),
)


def default_checks() -> list[IntegrationCheck]:
    return [IntegrationCheck(check_id=x, title=y) for x, y in REQUIRED_CHECKS]


def evaluate_integration(checks: Iterable[IntegrationCheck]) -> dict:
    rows = list(checks)
    by_id = {x.check_id: x for x in rows}
    missing = [cid for cid, _ in REQUIRED_CHECKS if cid not in by_id]
    failed = [x.check_id for x in rows if x.required and x.state == BLOCKED]
    unchecked = [x.check_id for x in rows if x.required and x.state != PASS and x.state != BLOCKED]
    no_evidence = [x.check_id for x in rows if x.required and x.state == PASS and not x.evidence.strip()]

    ready = not missing and not failed and not unchecked and not no_evidence
    return {
        "schema": "pc-backup-vault.integration-gate.v1",
        "state": "READY_FOR_MERGE_REVIEW" if ready else "MERGE_BLOCKED",
        "checks": [asdict(x) for x in rows],
        "missing": missing,
        "failed": failed,
        "unchecked": unchecked,
        "pass_without_evidence": no_evidence,
        "safety": {
            "merge_automatic": False,
            "release_automatic": False,
            "main_may_change": ready,
            "backup_core_may_change": False,
        },
        "rule": "Sprint 8 öffnet main erst nach vollständigen, belegten Integrationsprüfungen. Ein grüner Project-Finder-Test allein reicht ausdrücklich nicht.",
    }


def merge_gate_from_evidence(evidence: dict[str, tuple[str, str]]) -> dict:
    checks = []
    for cid, title in REQUIRED_CHECKS:
        state, proof = evidence.get(cid, (NOT_CHECKED, ""))
        checks.append(IntegrationCheck(cid, title, state, proof))
    return evaluate_integration(checks)
