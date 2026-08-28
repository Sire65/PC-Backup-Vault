from __future__ import annotations

import re
from typing import Iterable

from .project_names import canonical_project

STOP = {"aber","auch","dann","dass","eine","einer","einen","einem","eines","für","hier","jetzt","kann","machen","mehr","muss","nicht","noch","oder","soll","sollen","und","wenn","werden","wird","bitte","weiter","programm","projekt","bauen","einbauen","funktion","funktioniert"}
STRONG_EVIDENCE_KINDS = {"content", "commit", "test", "manual"}
WEAK_EVIDENCE_KINDS = {"filename", "path"}


def tokens(text: str) -> list[str]:
    words = re.findall(r"[a-zA-Z0-9äöüÄÖÜß_-]{3,}", text.lower())
    return [w for w in words if w not in STOP and not w.isdigit()]


def _evidence_row(value) -> dict:
    # Legacy strings historically represented searched file/content text. Keep that
    # compatibility as content; new callers should provide an explicit kind.
    if isinstance(value, dict):
        kind = str(value.get("kind") or "unknown").lower().strip()
        text = str(value.get("text") or value.get("value") or "")
        ref = str(value.get("ref") or "")
        return {"kind": kind, "text": text, "ref": ref}
    return {"kind": "content", "text": str(value), "ref": "legacy-string"}


def match_requirement(requirement: str, evidence_texts: Iterable, *, min_distinct: int = 2) -> dict:
    """Conservative lexical evidence. Filename/path-only evidence can never be FOUND."""
    req = list(dict.fromkeys(tokens(requirement)))
    evidence = [_evidence_row(x) for x in evidence_texts]
    evidence = [x for x in evidence if x["text"].strip()]
    if not evidence or not req:
        return {"state":"NOT_CHECKED","score":0,"matched_terms":[],"evidence_index":None,"evidence_kind":None,"evidence_ref":""}
    best = (0, [], None, None)
    for idx, row in enumerate(evidence):
        present=set(tokens(row["text"])); matched=[term for term in req if term in present]; score=round(100*len(matched)/max(len(req),1))
        candidate=(score, matched, idx, row)
        if len(matched)>len(best[1]) or (len(matched)==len(best[1]) and score>best[0]): best=candidate
    score, matched, idx, row = best; required=min(min_distinct,len(req)); lexical_ok=len(matched)>=required and score>=35
    kind=row["kind"] if row else "unknown"
    if lexical_ok and kind in STRONG_EVIDENCE_KINDS: state="FOUND"
    elif lexical_ok and kind in WEAK_EVIDENCE_KINDS: state="WEAK_ONLY"
    else: state="MISSING"
    return {"state":state,"score":score,"matched_terms":matched,"evidence_index":idx,"evidence_kind":kind,"evidence_ref":row.get("ref","") if row else ""}


def annotate_findings(findings: Iterable[dict], evidence_by_project: dict[str, Iterable]) -> list[dict]:
    normalized_evidence={canonical_project(k):v for k,v in evidence_by_project.items()}; rows=[]
    for finding in findings:
        row=dict(finding); project=canonical_project(row.get("project")); row["project"]=project
        result=match_requirement(str(row.get("text") or row.get("title") or ""),normalized_evidence.get(project,()))
        row["git_requirement_match"]=result["state"]; row["git_requirement_match_score"]=result["score"]; row["git_requirement_match_terms"]=result["matched_terms"]
        row["git_requirement_match_evidence_index"]=result["evidence_index"]; row["git_requirement_match_evidence_kind"]=result["evidence_kind"]; row["git_requirement_match_evidence_ref"]=result["evidence_ref"]
        rows.append(row)
    return rows
