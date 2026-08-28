from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable


def _rows(inventory: dict) -> list[dict]:
    return [dict(x) for x in inventory.get("findings", []) if isinstance(x, dict)]


def build_chat_summary(inventory: dict) -> dict:
    return {
        "schema": "pc-backup-vault.chat-summary.v1",
        "source": inventory.get("source"),
        "conversation_count": inventory.get("conversation_count", 0),
        "selected_count": inventory.get("selected_count", 0),
        "classifications": dict(inventory.get("classifications") or {}),
        "projects": dict(inventory.get("projects") or {}),
        "privacy": dict(inventory.get("privacy") or {}),
        "rule": inventory.get("rule"),
    }


def build_requirements(inventory: dict) -> dict:
    findings = _rows(inventory)
    keep = {"IDEA_OR_REQUIREMENT", "OPEN_OR_ERROR", "IMPLEMENTATION_CLAIM", "REJECTED_OR_REPLACED"}
    rows = []
    for row in findings:
        if row.get("kind") not in keep:
            continue
        rows.append({
            "conversation_id": row.get("conversation_id"),
            "message_id": row.get("message_id"),
            "timestamp": row.get("timestamp"),
            "project": row.get("project"),
            "kind": row.get("kind"),
            "text": row.get("text"),
            "evidence_strength": row.get("evidence_strength"),
        })
    return {
        "schema": "pc-backup-vault.requirements.v1",
        "count": len(rows),
        "requirements": rows,
        "rule": "Chat-Aussagen sind Hinweise; technische Umsetzung wird separat mit Git, lokalem Stand und Tests abgeglichen.",
    }


def write_analysis_bundle(inventory: dict, output_dir: str) -> dict:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    summary_file = out / "chat_summary.json"
    requirements_file = out / "requirements.json"
    csv_file = out / "chat_findings.csv"

    summary_file.write_text(json.dumps(build_chat_summary(inventory), ensure_ascii=False, indent=2), encoding="utf-8")
    requirements_file.write_text(json.dumps(build_requirements(inventory), ensure_ascii=False, indent=2), encoding="utf-8")

    fields = ["conversation_id", "message_id", "role", "title", "timestamp", "project", "kind", "text", "evidence_strength"]
    with csv_file.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore", delimiter=";")
        writer.writeheader()
        writer.writerows(_rows(inventory))

    return {
        "summary": str(summary_file),
        "requirements": str(requirements_file),
        "findings_csv": str(csv_file),
        "raw_chat_export_copied": False,
    }
