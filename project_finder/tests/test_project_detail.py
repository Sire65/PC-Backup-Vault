from project_finder.project_detail import build_project_detail


def test_project_detail_keeps_critical_evidence_visible():
    development = {
        "items": [
            {"project": "DP2 / Dienstplan", "status": "GREEN", "requirement": "A", "git_evidence": "FOUND", "test_evidence": "PASS", "local_git_relation": "SAME"},
            {"project": "DP2 / Dienstplan", "status": "RED", "requirement": "B", "reason": "Lokaler Stand neuer", "local_evidence": "FOUND", "local_git_relation": "LOCAL_NEWER"},
        ]
    }
    chat = {
        "findings": [
            {"project": "DP2 / Dienstplan", "kind": "IDEA_OR_REQUIREMENT", "title": "Plan", "text": "Neue Funktion", "conversation_id": "c1", "message_id": "m1"}
        ]
    }
    detail = build_project_detail("DP2 / Dienstplan", development, chat)
    assert detail["status"] == "RED"
    assert detail["counts"]["GREEN"] == 1
    assert detail["counts"]["RED"] == 1
    assert detail["evidence_rows"][1]["local_git_relation"] == "LOCAL_NEWER"
    assert detail["chat_sources"][0]["message_id"] == "m1"
    assert detail["traceability"] == "FALLBACK"
    assert detail["trust"]["chat_claims_are_not_proof"] is True


def test_project_detail_prefers_exact_reconciliation_source():
    development = {
        "items": [{"project": "KC Verwaltung", "status": "YELLOW", "requirement": "Filter"}],
        "details": [{
            "project": "KC Verwaltung", "status": "YELLOW", "requirement": "Filter", "reason": "Git noch nicht geprüft",
            "source": {"conversation_id": "c7", "message_id": "m9", "title": "Verwaltung", "kind": "IDEA_OR_REQUIREMENT", "evidence_strength": "HIGH"},
        }],
    }
    detail = build_project_detail("KC Verwaltung", development, {"findings": []})
    assert detail["schema"] == "pc-backup-vault.project-detail.v2"
    assert detail["traceability"] == "EXACT"
    assert detail["chat_sources"][0]["conversation_id"] == "c7"
    assert detail["chat_sources"][0]["message_id"] == "m9"
    assert detail["chat_sources"][0]["reason"] == "Git noch nicht geprüft"


def test_project_detail_does_not_invent_evidence():
    detail = build_project_detail("Unbekannt")
    assert detail["status"] == "YELLOW"
    assert detail["evidence_rows"] == []
    assert detail["chat_sources"] == []
    assert detail["traceability"] == "NONE"
