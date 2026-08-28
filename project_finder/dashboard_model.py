from __future__ import annotations

from collections import Counter, defaultdict
from typing import Iterable


def _project_status(row: dict) -> str:
    if row["red"]:
        return "RED"
    if row["yellow"]:
        return "YELLOW"
    if row["green"] and not row["yellow"] and not row["red"]:
        return "GREEN"
    if row["blue"] and not row["green"]:
        return "BLUE"
    return "YELLOW"


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
        "git_found": 0, "local_found": 0, "tests_pass": 0, "tests_fail": 0,
        "local_newer": 0, "diverged": 0, "status": "YELLOW",
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
        if item.get("git_evidence") == "FOUND":
            row["git_found"] += 1
        if item.get("local_evidence") == "FOUND":
            row["local_found"] += 1
        if item.get("test_evidence") == "PASS":
            row["tests_pass"] += 1
        if item.get("test_evidence") == "FAIL":
            row["tests_fail"] += 1
        if item.get("local_git_relation") == "LOCAL_NEWER":
            row["local_newer"] += 1
        if item.get("local_git_relation") == "DIVERGED":
            row["diverged"] += 1

    for row in project_rows.values():
        row["status"] = _project_status(row)

    priorities = sorted(
        project_rows.values(),
        key=lambda r: (r["red"] * 8 + r["tests_fail"] * 8 + r["local_newer"] * 7 + r["diverged"] * 7 + r["open"] * 4 + r["yellow"] * 2 + r["chat_findings"]),
        reverse=True,
    )

    return {
        "schema": "pc-backup-vault.project-dashboard.v2",
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
            "projects_red": sum(1 for x in project_rows.values() if x["status"] == "RED"),
            "projects_yellow": sum(1 for x in project_rows.values() if x["status"] == "YELLOW"),
            "projects_green": sum(1 for x in project_rows.values() if x["status"] == "GREEN"),
        },
        "file_categories": dict(categories),
        "development": dev_counts,
        "projects": priorities,
        "trust": {
            "real_data_only": True,
            "chat_claims_are_not_proof": True,
            "green_requires_technical_evidence": True,
        },
    }
