from __future__ import annotations

from dataclasses import asdict
from typing import Iterable

from .development_center import DevelopmentItem, decide_status
from .git_inventory import RepoSnapshot


CHAT_KIND_TO_CLAIM = {
    "IMPLEMENTATION_CLAIM": "IMPLEMENTED",
    "OPEN_OR_ERROR": "OPEN",
    "IDEA_OR_REQUIREMENT": "IDEA",
    "REJECTED_OR_REPLACED": "REJECTED",
}


def _requirement_text(row: dict) -> str:
    text = " ".join(str(row.get("text") or "").split())
    return text[:500] or str(row.get("title") or "Unbenannter Fund")


def reconcile_evidence(
    chat_findings: Iterable[dict],
    repo_rows: Iterable[RepoSnapshot | dict],
    local_projects: Iterable[dict] = (),
) -> dict:
    """Combine chat evidence, Git state, local scan state and tests.

    Project-level repository presence is never treated as proof that a concrete
    requirement exists in code. Exact source references are retained so every
    dashboard row can be traced back to the chat finding that created it.
    """
    repos: dict[str, RepoSnapshot] = {}
    for raw in repo_rows:
        repo = raw if isinstance(raw, RepoSnapshot) else RepoSnapshot(**raw)
        repos[repo.project] = repo

    local: dict[str, dict] = {}
    for row in local_projects:
        project = str(row.get("project") or "")
        if project:
            local[project] = dict(row)

    items: list[DevelopmentItem] = []
    details: list[dict] = []
    for finding in chat_findings:
        project = str(finding.get("project") or "Unbekannt")
        claim = CHAT_KIND_TO_CLAIM.get(str(finding.get("kind") or ""), "UNKNOWN")
        repo = repos.get(project)
        loc = local.get(project, {})

        requirement_match = str(finding.get("git_requirement_match") or "NOT_CHECKED")
        git_evidence = requirement_match if requirement_match in {"FOUND", "MISSING"} else "NOT_CHECKED"
        if not repo and git_evidence == "NOT_CHECKED":
            git_evidence = "MISSING"

        local_evidence = str(loc.get("evidence") or "NOT_CHECKED")
        if local_evidence not in {"FOUND", "MISSING", "NOT_CHECKED"}:
            local_evidence = "NOT_CHECKED"

        local_relation = "NOT_CHECKED"
        test_evidence = "NOT_CHECKED"
        build_evidence = "NOT_CHECKED"
        if repo:
            local_relation = repo.local_state or "NOT_CHECKED"
            test_evidence = repo.latest_test or "NOT_CHECKED"
            build_evidence = "FOUND" if (repo.version or repo.build or repo.head_sha) else "NOT_CHECKED"

        item = decide_status(DevelopmentItem(
            project=project,
            requirement=_requirement_text(finding),
            chat_claim=claim,
            git_evidence=git_evidence,
            local_evidence=local_evidence,
            test_evidence=test_evidence,
            local_git_relation=local_relation,
            build_evidence=build_evidence,
        ))
        items.append(item)
        details.append({
            "project": project,
            "requirement": item.requirement,
            "status": item.status,
            "reason": item.reason,
            "chat_claim": item.chat_claim,
            "git_evidence": item.git_evidence,
            "local_evidence": item.local_evidence,
            "test_evidence": item.test_evidence,
            "build_evidence": item.build_evidence,
            "local_git_relation": item.local_git_relation,
            "source": {
                "conversation_id": str(finding.get("conversation_id") or ""),
                "message_id": str(finding.get("message_id") or ""),
                "title": str(finding.get("title") or ""),
                "timestamp": finding.get("timestamp"),
                "kind": str(finding.get("kind") or ""),
                "evidence_strength": str(finding.get("evidence_strength") or ""),
            },
        })

    counts = {"GREEN": 0, "YELLOW": 0, "RED": 0, "BLUE": 0}
    for item in items:
        counts[item.status] = counts.get(item.status, 0) + 1

    return {
        "schema": "pc-backup-vault.evidence-reconciliation.v2",
        "counts": counts,
        "items": [asdict(x) for x in items],
        "details": details,
        "evidence": {
            "chat_findings": len(items),
            "git_projects": len(repos),
            "local_projects": len(local),
        },
        "trust": {
            "chat_claims_are_not_proof": True,
            "project_repo_presence_is_not_requirement_proof": True,
            "source_traceability": True,
        },
        "rule": "Projekt in Git gefunden bedeutet nicht automatisch, dass eine konkrete Chat-Anforderung umgesetzt ist. GREEN braucht Anforderungsnachweis plus grüne Tests und darf keinen neueren/abweichenden lokalen Stand haben.",
    }
