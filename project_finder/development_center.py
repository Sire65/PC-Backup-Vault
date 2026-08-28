from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Iterable


@dataclass
class DevelopmentItem:
    project: str
    requirement: str
    chat_claim: str = "UNKNOWN"
    git_evidence: str = "NOT_CHECKED"
    local_evidence: str = "NOT_CHECKED"
    test_evidence: str = "NOT_CHECKED"
    local_git_relation: str = "NOT_CHECKED"  # SAME, LOCAL_NEWER, GIT_NEWER, DIVERGED
    build_evidence: str = "NOT_CHECKED"      # FOUND, MISSING, NOT_CHECKED
    status: str = "YELLOW"
    reason: str = "Noch nicht vollständig abgeglichen."


def decide_status(item: DevelopmentItem) -> DevelopmentItem:
    """Conservative evidence reconciliation.

    GREEN is deliberately difficult: Git evidence + passing tests are required,
    and a newer/diverged local state always blocks green. Chat claims alone are
    never technical proof.
    """
    if item.chat_claim == "REJECTED":
        item.status = "BLUE"
        item.reason = "Verworfen oder durch andere Lösung ersetzt."
        return item

    if item.local_git_relation == "DIVERGED":
        item.status = "RED"
        item.reason = "Lokaler und Git-Stand sind abgewichen; möglicher nicht gesicherter Entwicklungszweig."
        return item

    if item.local_git_relation == "LOCAL_NEWER":
        item.status = "RED"
        item.reason = "Lokaler Stand ist neuer als Git; mögliche noch nicht gesicherte Entwicklung."
        return item

    if item.git_evidence == "MISSING" and item.local_evidence == "FOUND":
        item.status = "RED"
        item.reason = "Mögliche verlorene Entwicklung: lokal gefunden, in Git nicht vorhanden."
        return item

    if item.test_evidence == "FAIL":
        item.status = "RED"
        item.reason = "Technischer Nachweis vorhanden, aber Regression/Test ist fehlgeschlagen."
        return item

    if item.git_evidence == "FOUND" and item.test_evidence == "PASS":
        if item.local_git_relation in {"SAME", "GIT_NEWER"}:
            item.status = "GREEN"
            item.reason = "Git-Nachweis und grüne Tests vorhanden; kein neuerer lokaler Stand erkannt."
            return item
        item.status = "YELLOW"
        item.reason = "Git und Tests sind grün, aber der lokale Vergleich ist noch nicht eindeutig."
        return item

    if item.chat_claim == "IMPLEMENTED" and item.git_evidence in {"MISSING", "NOT_CHECKED"}:
        item.status = "YELLOW"
        item.reason = "Chat behauptet Umsetzung, aber technischer Nachweis fehlt."
        return item

    if item.chat_claim in {"OPEN", "IDEA"} and item.git_evidence == "MISSING":
        # A missing idea is not automatically a lost development. It may simply
        # be planned work that was never implemented.
        item.status = "YELLOW"
        item.reason = "Geplant/offen; im Git-Stand nicht gefunden. Noch kein Beleg für verlorene Entwicklung."
        return item

    item.status = "YELLOW"
    item.reason = "Teilweise oder widersprüchliche Nachweise; Vergleich erforderlich."
    return item


def summarize(items: Iterable[DevelopmentItem]) -> dict:
    rows = [decide_status(x) for x in items]
    counts = {"GREEN": 0, "YELLOW": 0, "RED": 0, "BLUE": 0}
    for row in rows:
        counts[row.status] = counts.get(row.status, 0) + 1
    return {
        "schema": "pc-backup-vault.development-center.v2",
        "counts": counts,
        "items": [asdict(x) for x in rows],
        "rules": {
            "chat_is_proof": False,
            "green_requires_test_pass": True,
            "local_newer_blocks_green": True,
            "diverged_blocks_green": True,
            "idea_missing_is_not_lost_development": True,
        },
    }
