from dataclasses import dataclass

from project_finder.inventory_github_dashboard_model import build_inventory_github_dashboard


@dataclass
class Item:
    path: str
    name: str
    size: int
    category: str = "source"
    duplicate_of: str = ""
    status: str = "GREEN"
    score: int = 80
    version_hint: str = ""
    modified_iso: str = "2026-08-29T12:00:00"


def test_dashboard_empty_is_safe():
    model = build_inventory_github_dashboard([], None)
    assert model["kpi"]["files"] == 0
    assert model["kpi"]["github_compared"] == 0
    assert model["kpi"]["github_ok_percent"] == 0.0
    assert model["safety"]["automatic_main_write"] is False


def test_dashboard_aggregates_github_states_and_repo_health(monkeypatch):
    items = [
        Item(path="C:/DP2/app.py", name="app.py", size=100),
        Item(path="C:/DP2/old.py", name="old.py", size=50, duplicate_of="C:/DP2/app.py"),
    ]

    # Make the unit test independent of decision-engine heuristics; those are covered separately.
    monkeypatch.setattr(
        "project_finder.decision_engine.classify_inventory",
        lambda _items: [
            {"path": "C:/DP2/app.py", "git_action": "TO_GIT", "inventory_action": "KEEP"},
            {"path": "C:/DP2/old.py", "git_action": "REVIEW", "inventory_action": "QUARANTINE_CANDIDATE"},
        ],
    )
    report = {
        "items": [
            {"repo": "Sire65/Dienstplan", "state": "IDENTICAL"},
            {"repo": "Sire65/Dienstplan", "state": "LOCAL_ONLY"},
            {"repo": "Sire65/Kasse", "state": "DIVERGENT"},
        ]
    }

    model = build_inventory_github_dashboard(items, report)
    k = model["kpi"]
    assert k["files"] == 2
    assert k["bytes"] == 150
    assert k["duplicates"] == 1
    assert k["duplicate_bytes"] == 50
    assert k["to_git"] == 1
    assert k["git_review"] == 1
    assert k["quarantine_candidates"] == 1
    assert k["github_compared"] == 3
    assert k["github_identical"] == 1
    assert k["github_local_only"] == 1
    assert k["github_divergent"] == 1
    assert k["repositories"] == 2
    assert k["github_ok_percent"] == 33.3

    by_repo = {row["repo"]: row for row in model["repositories"]}
    assert by_repo["Sire65/Dienstplan"]["status"] == "YELLOW"
    assert by_repo["Sire65/Kasse"]["status"] == "RED"
