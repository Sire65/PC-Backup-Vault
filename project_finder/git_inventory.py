from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable


@dataclass
class RepoSnapshot:
    project: str
    repository: str
    default_branch: str = "main"
    head_sha: str = ""
    version: str = ""
    build: str = ""
    latest_test: str = "NOT_CHECKED"
    release_state: str = "UNKNOWN"
    local_state: str = "NOT_CHECKED"
    update_mode: str = "UNKNOWN"
    notes: str = ""


def summarize_repositories(rows: Iterable[RepoSnapshot]) -> dict:
    repos = list(rows)
    return {
        "schema": "pc-backup-vault.git-inventory.v1",
        "repositories": [asdict(x) for x in repos],
        "counts": {
            "total": len(repos),
            "tests_pass": sum(1 for x in repos if x.latest_test == "PASS"),
            "tests_fail": sum(1 for x in repos if x.latest_test == "FAIL"),
            "update_ready": sum(1 for x in repos if x.update_mode in {"AUTO", "CHECK_AND_INSTALL"}),
            "local_newer": sum(1 for x in repos if x.local_state == "LOCAL_NEWER"),
            "git_newer": sum(1 for x in repos if x.local_state == "GIT_NEWER"),
            "diverged": sum(1 for x in repos if x.local_state == "DIVERGED"),
        },
    }


def update_readiness(row: RepoSnapshot) -> tuple[str, str]:
    if row.latest_test == "FAIL":
        return "RED", "Aktueller Git-Stand hat fehlgeschlagene Tests."
    if row.local_state == "LOCAL_NEWER":
        return "YELLOW", "Lokaler Stand ist neuer als Git; zuerst sichern/vergleichen."
    if row.local_state == "DIVERGED":
        return "RED", "Git und lokaler Stand sind auseinander gelaufen."
    if not row.head_sha:
        return "YELLOW", "Kein eindeutiger Git-HEAD bekannt."
    if row.latest_test == "PASS" and row.update_mode in {"AUTO", "CHECK_AND_INSTALL"}:
        return "GREEN", "Getesteter Git-Stand und Update-Pfad vorhanden."
    return "YELLOW", "Weitere Prüfung vor automatischer Update-Verteilung erforderlich."
