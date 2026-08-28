from __future__ import annotations

import re
from typing import Iterable

from .project_names import canonical_project

STOP = {
    "aber", "auch", "dann", "dass", "eine", "einer", "einen", "einem", "eines",
    "für", "hier", "jetzt", "kann", "machen", "mehr", "muss", "nicht", "noch",
    "oder", "soll", "sollen", "und", "wenn", "werden", "wird", "bitte", "weiter",
    "programm", "projekt", "bauen", "einbauen", "funktion", "funktioniert",
}


def tokens(text: str) -> list[str]:
    words = re.findall(r"[a-zA-Z0-9äöüÄÖÜß_-]{3,}", text.lower())
    return [w for w in words if w not in STOP and not w.isdigit()]


def match_requirement(requirement: str, evidence_texts: Iterable[str], *, min_distinct: int = 2) -> dict:
    """Return conservative lexical evidence for one requirement.

    FOUND is only lexical evidence, never implementation proof by itself. The
    reconciliation layer still requires green tests and a safe local/Git relation.
    """
    req = list(dict.fromkeys(tokens(requirement)))
    evidence = [str(x) for x in evidence_texts if str(x).strip()]
    if not evidence or not req:
        return {"state": "NOT_CHECKED", "score": 0, "matched_terms": [], "evidence_index": None}

    best = (0, [], None)
    for idx, text in enumerate(evidence):
        present = set(tokens(text))
        matched = [term for term in req if term in present]
        score = round(100 * len(matched) / max(len(req), 1))
        if len(matched) > len(best[1]):
            best = (score, matched, idx)

    score, matched, idx = best
    required = min(min_distinct, len(req))
    state = "FOUND" if len(matched) >= required and score >= 35 else "MISSING"
    return {"state": state, "score": score, "matched_terms": matched, "evidence_index": idx}


def annotate_findings(findings: Iterable[dict], evidence_by_project: dict[str, Iterable[str]]) -> list[dict]:
    normalized_evidence = {canonical_project(k): v for k, v in evidence_by_project.items()}
    rows = []
    for finding in findings:
        row = dict(finding)
        project = canonical_project(row.get("project"))
        row["project"] = project
        result = match_requirement(
            str(row.get("text") or row.get("title") or ""),
            normalized_evidence.get(project, ()),
        )
        row["git_requirement_match"] = result["state"]
        row["git_requirement_match_score"] = result["score"]
        row["git_requirement_match_terms"] = result["matched_terms"]
        row["git_requirement_match_evidence_index"] = result["evidence_index"]
        rows.append(row)
    return rows
