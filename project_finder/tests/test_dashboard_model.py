from dataclasses import dataclass

from project_finder.dashboard_model import build_dashboard


@dataclass
class Item:
    size: int
    category: str
    duplicate_of: str = ""
    version_hint: str = ""


def test_dashboard_uses_real_input_counts_only():
    scan = [
        Item(100, "source", version_hint="1.0.0"),
        Item(100, "source", duplicate_of="a.py", version_hint="1.0.0"),
        Item(300, "archive"),
    ]
    chat = {
        "conversation_count": 20,
        "classifications": {"development": 5, "possible_development": 2, "other": 13},
        "projects": {"DP2 / Dienstplan": {"ideas": 3, "implementation_claims": 2, "open_or_error": 4, "rejected": 1}},
        "findings": [{}] * 10,
    }
    development = {
        "counts": {"GREEN": 6, "YELLOW": 3, "RED": 1, "BLUE": 0},
        "items": [
            {"project": "DP2 / Dienstplan", "status": "GREEN"},
            {"project": "DP2 / Dienstplan", "status": "RED"},
        ],
    }
    model = build_dashboard(scan_items=scan, chat_inventory=chat, development_summary=development)
    assert model["kpi"]["files"] == 3
    assert model["kpi"]["bytes"] == 500
    assert model["kpi"]["duplicates"] == 1
    assert model["kpi"]["duplicate_bytes"] == 100
    assert model["kpi"]["projects"] == 1
    assert model["kpi"]["chats_development"] == 5
    assert model["kpi"]["chat_findings"] == 10
    assert model["kpi"]["proven_percent"] == 60.0
    assert model["kpi"]["open_or_lost"] == 1


def test_empty_dashboard_never_invents_data():
    model = build_dashboard()
    assert model["kpi"]["files"] == 0
    assert model["kpi"]["projects"] == 0
    assert model["kpi"]["chat_findings"] == 0
    assert model["kpi"]["proven_percent"] == 0.0
