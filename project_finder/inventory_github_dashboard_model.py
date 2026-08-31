from __future__ import annotations

from collections import Counter, defaultdict
from typing import Iterable


def build_inventory_github_dashboard(items: Iterable | None = None, github_report: dict | None = None) -> dict:
    """Build read-only KPI data for inventory and GitHub management.

    The model only evaluates results already produced by Project Finder and the
    read-only GitHub comparison. It performs no file or GitHub writes.
    """
    items = list(items or [])
    github_report = github_report or {}
    comparisons = list(github_report.get("items") or github_report.get("comparisons") or [])

    inventory = Counter()
    git_actions = Counter()
    categories = Counter()
    total_bytes = 0
    duplicate_bytes = 0

    # Keep this import local so the pure model remains cheap to import in tests/UI startup.
    try:
        from .decision_engine import classify_inventory
        classified = classify_inventory(items)
    except Exception:
        classified = []

    by_path = {str(row.get("path", "")): row for row in classified}
    for item in items:
        total_bytes += int(getattr(item, "size", 0) or 0)
        categories[str(getattr(item, "category", "other") or "other")] += 1
        if getattr(item, "duplicate_of", ""):
            duplicate_bytes += int(getattr(item, "size", 0) or 0)
        row = by_path.get(str(getattr(item, "path", "")), {})
        inventory[str(row.get("inventory_action") or "UNCLASSIFIED")] += 1
        git_actions[str(row.get("git_action") or "UNCLASSIFIED")] += 1

    github_states = Counter()
    repos = defaultdict(lambda: Counter())
    for row in comparisons:
        state = str(row.get("state") or "UNKNOWN")
        github_states[state] += 1
        repo = str(row.get("repo") or row.get("repository") or row.get("repo_name") or "Unzugeordnet")
        repos[repo][state] += 1
        repos[repo]["TOTAL"] += 1

    project_rows = []
    for repo, counts in repos.items():
        problem = counts["DIVERGENT"] + counts["REPO_UNAVAILABLE"]
        pending = counts["LOCAL_ONLY"] + counts["POSSIBLE_MATCH"] + counts["UNASSIGNED"]
        if problem:
            status = "RED"
        elif pending:
            status = "YELLOW"
        else:
            status = "GREEN"
        project_rows.append({
            "repo": repo,
            "status": status,
            "total": counts["TOTAL"],
            "identical": counts["IDENTICAL"],
            "local_only": counts["LOCAL_ONLY"],
            "divergent": counts["DIVERGENT"],
            "possible": counts["POSSIBLE_MATCH"],
            "unavailable": counts["REPO_UNAVAILABLE"],
            "unassigned": counts["UNASSIGNED"],
        })
    project_rows.sort(key=lambda r: (r["status"] != "RED", r["status"] != "YELLOW", -r["divergent"], -r["local_only"], r["repo"].lower()))

    to_git = git_actions["TO_GIT"]
    git_review = git_actions["REVIEW"]
    never_git = git_actions["NEVER"]
    keep_local = inventory["KEEP_LOCAL"]
    review = inventory["REVIEW"]
    quarantine = inventory["QUARANTINE_CANDIDATE"]
    duplicates = sum(1 for x in items if getattr(x, "duplicate_of", ""))

    compared = sum(github_states.values())
    healthy = github_states["IDENTICAL"]
    github_ok_pct = round(healthy / compared * 100.0, 1) if compared else 0.0

    return {
        "schema": "pc-backup-vault.inventory-github-dashboard.v1",
        "kpi": {
            "files": len(items),
            "bytes": total_bytes,
            "duplicates": duplicates,
            "duplicate_bytes": duplicate_bytes,
            "to_git": to_git,
            "git_review": git_review,
            "never_git": never_git,
            "keep_local": keep_local,
            "inventory_review": review,
            "quarantine_candidates": quarantine,
            "github_compared": compared,
            "github_identical": github_states["IDENTICAL"],
            "github_local_only": github_states["LOCAL_ONLY"],
            "github_divergent": github_states["DIVERGENT"],
            "github_possible": github_states["POSSIBLE_MATCH"],
            "github_unavailable": github_states["REPO_UNAVAILABLE"],
            "github_unassigned": github_states["UNASSIGNED"],
            "github_ok_percent": github_ok_pct,
            "repositories": len(project_rows),
        },
        "inventory_actions": dict(inventory),
        "git_actions": dict(git_actions),
        "github_states": dict(github_states),
        "categories": dict(categories),
        "repositories": project_rows,
        "safety": {
            "read_only_model": True,
            "automatic_delete": False,
            "automatic_main_write": False,
        },
    }
