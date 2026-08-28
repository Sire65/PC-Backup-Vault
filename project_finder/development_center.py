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
    status: str = "YELLOW"
    reason: str = "Noch nicht vollständig abgeglichen."


def decide_status(item: DevelopmentItem) -> DevelopmentItem:
    if item.chat_claim == "REJECTED":
        item.status = "BLUE"
        item.reason = "Verworfen oder durch andere Lösung ersetzt."
        return item
    if item.git_evidence == "FOUND" and item.test_evidence == "PASS":
        item.status = "GREEN"
        item.reason = "Code/Build und Testnachweis vorhanden."
        return item
    if item.git_evidence == "MISSING" and item.local_evidence == "FOUND":
        item.status = "RED"
        item.reason = "Mögliche verlorene Entwicklung: lokal gefunden, in Git nicht vorhanden."
        return item
    if item.chat_claim == "IMPLEMENTED" and item.git_evidence in {"MISSING", "NOT_CHECKED"}:
        item.status = "YELLOW"
        item.reason = "Chat behauptet Umsetzung, aber technischer Nachweis fehlt."
        return item
    if item.chat_claim in {"OPEN", "IDEA"} and item.git_evidence == "MISSING":
        item.status = "RED"
        item.reason = "Geplant/offen und im aktuellen Git-Stand nicht gefunden."
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
        "schema": "pc-backup-vault.development-center.v1",
        "counts": counts,
        "items": [asdict(x) for x in rows],
    }
