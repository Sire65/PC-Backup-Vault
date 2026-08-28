from __future__ import annotations

from collections import Counter
from typing import Iterable


def summarize_changes(findings: Iterable[dict]) -> dict:
    rows = list(findings)
    kinds = Counter(str(x.get("kind") or "UNKNOWN") for x in rows)
    projects = Counter(str(x.get("project") or "Unbekannt") for x in rows)
    risk = sum(1 for x in rows if x.get("kind") == "OPEN_OR_ERROR")
    claimed = sum(1 for x in rows if x.get("kind") == "IMPLEMENTATION_CLAIM")
    ideas = sum(1 for x in rows if x.get("kind") == "IDEA_OR_REQUIREMENT")
    rejected = sum(1 for x in rows if x.get("kind") == "REJECTED_OR_REPLACED")
    return {
        "schema": "pc-backup-vault.change-dashboard.v1",
        "counts": {
            "new": len(rows),
            "projects_affected": len([p for p in projects if p and p != "Unbekannt"]),
            "open_or_error": risk,
            "implementation_claims": claimed,
            "ideas": ideas,
            "rejected": rejected,
        },
        "kinds": dict(kinds),
        "projects": dict(projects.most_common()),
        "attention": [x for x in rows if x.get("kind") == "OPEN_OR_ERROR"],
    }
