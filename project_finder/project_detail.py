from __future__ import annotations

from collections import Counter


def _evidence_row(item: dict) -> dict:
    return {
        "status": str(item.get("status") or "YELLOW"),
        "requirement": str(item.get("requirement") or ""),
        "reason": str(item.get("reason") or ""),
        "chat_claim": str(item.get("chat_claim") or "UNKNOWN"),
        "git": str(item.get("git_evidence") or "NOT_CHECKED"),
        "local": str(item.get("local_evidence") or "NOT_CHECKED"),
        "test": str(item.get("test_evidence") or "NOT_CHECKED"),
        "build": str(item.get("build_evidence") or "NOT_CHECKED"),
        "local_git_relation": str(item.get("local_git_relation") or "NOT_CHECKED"),
    }


def build_project_detail(project: str, development_summary: dict | None = None, chat_inventory: dict | None = None) -> dict:
    development_summary = development_summary or {}
    chat_inventory = chat_inventory or {}
    items = [dict(x) for x in development_summary.get("items", []) if str(x.get("project") or "") == project]
    exact_details = [dict(x) for x in development_summary.get("details", []) if str(x.get("project") or "") == project]
    chat_findings = [dict(x) for x in chat_inventory.get("findings", []) if str(x.get("project") or "") == project]

    counts = Counter(str(x.get("status") or "YELLOW") for x in items)
    if counts["RED"]:
        status = "RED"
    elif counts["YELLOW"]:
        status = "YELLOW"
    elif counts["GREEN"]:
        status = "GREEN"
    elif counts["BLUE"]:
        status = "BLUE"
    else:
        status = "YELLOW"

    evidence_rows = [_evidence_row(item) for item in items]
    source_rows = []

    if exact_details:
        for detail in exact_details:
            source = dict(detail.get("source") or {})
            source_rows.append({
                "kind": str(source.get("kind") or ""),
                "title": str(source.get("title") or ""),
                "text": str(detail.get("requirement") or "")[:500],
                "conversation_id": str(source.get("conversation_id") or ""),
                "message_id": str(source.get("message_id") or ""),
                "timestamp": source.get("timestamp"),
                "evidence_strength": str(source.get("evidence_strength") or ""),
                "status": str(detail.get("status") or "YELLOW"),
                "reason": str(detail.get("reason") or ""),
            })
    else:
        for finding in chat_findings:
            source_rows.append({
                "kind": str(finding.get("kind") or ""),
                "title": str(finding.get("title") or ""),
                "text": str(finding.get("text") or "")[:500],
                "conversation_id": str(finding.get("conversation_id") or ""),
                "message_id": str(finding.get("message_id") or ""),
                "timestamp": finding.get("timestamp"),
                "evidence_strength": str(finding.get("evidence_strength") or ""),
                "status": "",
                "reason": "",
            })

    return {
        "schema": "pc-backup-vault.project-detail.v2",
        "project": project,
        "status": status,
        "counts": {key: int(counts.get(key, 0)) for key in ("GREEN", "YELLOW", "RED", "BLUE")},
        "evidence_rows": evidence_rows,
        "chat_sources": source_rows,
        "traceability": "EXACT" if exact_details else ("FALLBACK" if source_rows else "NONE"),
        "trust": {
            "chat_claims_are_not_proof": True,
            "no_simulated_data": True,
            "exact_source_preferred": True,
        },
    }
