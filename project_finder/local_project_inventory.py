from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Iterable

from .scanner import ScanItem

PROJECT_ALIASES = {
    "DP2": ("dp2", "dienstplan"),
    "PC Backup Vault": ("pc-backup-vault", "pc backup vault", "backup vault"),
    "KC Marktkasse": ("marktkasse", "bilderkasse", "kasse"),
    "KC Verwaltung": ("kc-verwaltung", "kc verwaltung", "verwaltung"),
    "KC Futura": ("kc-futura", "futura"),
    "KC Communication": ("kc-communication", "communication", "kommunikation"),
    "KC Leitstand": ("kc-leitstand", "leitstand"),
    "KC Money Butler": ("money-butler", "money butler", "moneybutler"),
}


def detect_project(path: str) -> str:
    low = path.lower().replace("_", " ")
    best = (0, "Unbekannt")
    for project, aliases in PROJECT_ALIASES.items():
        score = sum(1 for alias in aliases if alias in low)
        if score > best[0]:
            best = (score, project)
    return best[1]


def group_local_projects(items: Iterable[ScanItem | dict]) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for raw in items:
        row = asdict(raw) if isinstance(raw, ScanItem) else dict(raw)
        project = detect_project(str(row.get("path") or row.get("name") or ""))
        if project != "Unbekannt":
            groups[project].append(row)

    out = []
    for project, rows in sorted(groups.items()):
        newest = max(rows, key=lambda r: float(r.get("modified") or 0))
        versions = sorted({str(r.get("version_hint") or "") for r in rows if r.get("version_hint")})
        duplicate_count = sum(1 for r in rows if r.get("duplicate_of"))
        source_count = sum(1 for r in rows if r.get("category") == "source")
        archive_count = sum(1 for r in rows if r.get("category") == "archive")
        out.append({
            "project": project,
            "evidence": "FOUND",
            "file_count": len(rows),
            "source_count": source_count,
            "archive_count": archive_count,
            "duplicate_count": duplicate_count,
            "versions": versions,
            "newest_path": str(newest.get("path") or ""),
            "newest_modified": newest.get("modified_iso") or "",
            "newest_timestamp": float(newest.get("modified") or 0),
        })
    return out


def compare_local_to_git(local_row: dict, git_row: dict) -> str:
    """Conservative relation based only on evidence that actually exists.

    Version strings are not assumed semver-compatible. A known matching version is
    SAME; a differing known version is NOT_CHECKED unless timestamps/SHAs are
    provided by a stronger comparison stage.
    """
    local_versions = {str(v) for v in local_row.get("versions", []) if v}
    git_version = str(git_row.get("version") or "")
    if git_version and git_version in local_versions:
        return "SAME"
    local_sha = str(local_row.get("head_sha") or "")
    git_sha = str(git_row.get("head_sha") or "")
    if local_sha and git_sha:
        return "SAME" if local_sha == git_sha else "DIVERGED"
    return "NOT_CHECKED"
