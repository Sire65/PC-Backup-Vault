from __future__ import annotations

from dataclasses import asdict, fields
from typing import Iterable

from .development_center import DevelopmentItem, decide_status
from .git_inventory import RepoSnapshot
from .project_names import canonical_project


CHAT_KIND_TO_CLAIM = {
    "IMPLEMENTATION_CLAIM": "IMPLEMENTED",
    "OPEN_OR_ERROR": "OPEN",
    "IDEA_OR_REQUIREMENT": "IDEA",
    "REJECTED_OR_REPLACED": "REJECTED",
}


def _requirement_text(row: dict) -> str:
    text = " ".join(str(row.get("text") or "").split())
    return text[:500] or str(row.get("title") or "Unbenannter Fund")


def _repo_snapshot(raw: RepoSnapshot | dict) -> RepoSnapshot:
    if isinstance(raw, RepoSnapshot):
        raw.project = canonical_project(raw.project)
        return raw
    allowed = {x.name for x in fields(RepoSnapshot)}
    clean = {k: v for k, v in dict(raw).items() if k in allowed}
    clean["project"] = canonical_project(clean.get("project") or clean.get("repository"))
    clean.setdefault("repository", str(raw.get("repository") or ""))
    return RepoSnapshot(**clean)


def reconcile_evidence(
    chat_findings: Iterable[dict],
    repo_rows: Iterable[RepoSnapshot | dict],
    local_projects: Iterable[dict] = (),
) -> dict:
    """Combine chat, Git, local and test evidence without optimistic inference."""
    repos: dict[str, RepoSnapshot] = {}
    for raw in repo_rows:
        repo = _repo_snapshot(raw)
        repos[repo.project] = repo

    local: dict[str, dict] = {}
    for raw in local_projects:
        row = dict(raw)
        project = canonical_project(row.get("project"))
        if project != "Unbekannt":
            local[project] = row

    items: list[DevelopmentItem] = []
    for finding in chat_findings:
        project = canonical_project(finding.get("project"))
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

        item = DevelopmentItem(
            project=project,
            requirement=_requirement_text(finding),
            chat_claim=claim,
            git_evidence=git_evidence,
            local_evidence=local_evidence,
            test_evidence=test_evidence,
            local_git_relation=local_relation,
            build_evidence=build_evidence,
            source_conversation_id=str(finding.get("conversation_id") or ""),
            source_message_id=str(finding.get("message_id") or ""),
            source_title=str(finding.get("title") or ""),
            source_kind=str(finding.get("kind") or ""),
            source_evidence_strength=str(finding.get("evidence_strength") or ""),
        )
        items.append(decide_status(item))

    counts = {"GREEN": 0, "YELLOW": 0, "RED": 0, "BLUE": 0}
    for item in items:
        counts[item.status] = counts.get(item.status, 0) + 1

    return {
        "schema": "pc-backup-vault.evidence-reconciliation.v2",
        "counts": counts,
        "items": [asdict(x) for x in items],
        "evidence": {"chat_findings": len(items), "git_projects": len(repos), "local_projects": len(local)},
        "rule": "Git-Projekt allein beweist keine konkrete Anforderung. GREEN braucht expliziten Anforderungsnachweis, PASS und keinen neueren/abweichenden lokalen Stand.",
    }
