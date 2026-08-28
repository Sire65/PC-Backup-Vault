from __future__ import annotations

from collections import Counter, defaultdict
from typing import Iterable


def build_dashboard(*, scan_items: Iterable | None = None, chat_inventory: dict | None = None, development_summary: dict | None = None) -> dict:
    scan_items = list(scan_items or [])
    chat_inventory = chat_inventory or {}
    development_summary = development_summary or {"counts": {}, "items": []}

    total_bytes = sum(int(getattr(x, "size", 0) or 0) for x in scan_items)
    duplicates = [x for x in scan_items if getattr(x, "duplicate_of", "")]
    duplicate_bytes = sum(int(getattr(x, "size", 0) or 0) for x in duplicates)
    categories = Counter(getattr(x, "category", "other") for x in scan_items)
    versions = sum(1 for x in scan_items if getattr(x, "version_hint", ""))

    classif = chat_inventory.get("classifications", {})
    projects = chat_inventory.get("projects", {})
    findings = chat_inventory.get("findings", [])

    dev_counts = {k: int(v) for k, v in development_summary.get("counts", {}).items()}
    for key in ("GREEN", "YELLOW", "RED", "BLUE"):
        dev_counts.setdefault(key, 0)
    dev_total = sum(dev_counts.values())
    proven_pct = round((dev_counts["GREEN"] / dev_total * 100), 1) if dev_total else 0.0

    project_rows = defaultdict(lambda: {
        "project": "", "chat_findings": 0, "ideas": 0, "claims": 0,
        "open": 0, "rejected": 0, "green": 0, "yellow": 0, "red": 0, "blue": 0,
    })
    for project, stats in projects.items():
        row = project_rows[project]
        row["project"] = project
        row["ideas"] = int(stats.get("ideas", 0))
        row["claims"] = int(stats.get("implementation_claims", 0))
        row["open"] = int(stats.get("open_or_error", 0))
        row["rejected"] = int(stats.get("rejected", 0))
        row["chat_findings"] = row["ideas"] + row["claims"] + row["open"] + row["rejected"]

    for item in development_summary.get("items", []):
        project = str(item.get("project") or "Unzugeordnet")
        row = project_rows[project]
        row["project"] = project
        status = str(item.get("status") or "YELLOW").lower()
        if status in {"green", "yellow", "red", "blue"}:
            row[status] += 1

    priorities = sorted(
        project_rows.values(),
        key=lambda r: (r["red"] * 8 + r["open"] * 4 + r["yellow"] * 2 + r["chat_findings"]),
        reverse=True,
    )

    return {
        "schema": "pc-backup-vault.project-dashboard.v1",
        "kpi": {
            "files": len(scan_items),
            "bytes": total_bytes,
            "duplicates": len(duplicates),
            "duplicate_bytes": duplicate_bytes,
            "versioned_files": versions,
            "projects": len(project_rows),
            "chats_total": int(chat_inventory.get("conversation_count", 0)),
            "chats_development": int(classif.get("development", 0)),
            "chats_possible": int(classif.get("possible_development", 0)),
            "chat_findings": len(findings),
            "development_total": dev_total,
            "proven_percent": proven_pct,
            "open_or_lost": dev_counts["RED"],
            "needs_review": dev_counts["YELLOW"],
        },
        "file_categories": dict(categories),
        "development": dev_counts,
        "projects": priorities,
    }
