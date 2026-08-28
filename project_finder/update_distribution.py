from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Iterable


@dataclass
class UpdateTarget:
    project: str
    repository: str
    version: str = ""
    build: str = ""
    head_sha: str = ""
    test_state: str = "NOT_CHECKED"
    local_state: str = "NOT_CHECKED"
    update_mode: str = "UNKNOWN"


def evaluate_target(target: UpdateTarget) -> dict:
    state = "BLOCKED"
    reason = "Updatefreigabe fehlt."
    if not target.head_sha:
        reason = "Kein eindeutiger Git-Commit vorhanden."
    elif target.test_state != "PASS":
        reason = "Aktueller Git-Stand ist nicht durch grüne Tests freigegeben."
    elif target.local_state in {"LOCAL_NEWER", "DIVERGED"}:
        reason = "Lokaler Stand muss zuerst gesichert und abgeglichen werden."
    elif target.update_mode not in {"AUTO", "CHECK_AND_INSTALL"}:
        reason = "Für dieses Programm ist noch kein sicherer Update-Pfad definiert."
    else:
        state = "READY"
        reason = "Getesteter Git-Stand mit definiertem Update-Pfad."
    return {**asdict(target), "distribution_state": state, "reason": reason}


def build_update_plan(targets: Iterable[UpdateTarget]) -> dict:
    rows = [evaluate_target(x) for x in targets]
    return {
        "schema": "pc-backup-vault.update-plan.v1",
        "ready": [x for x in rows if x["distribution_state"] == "READY"],
        "blocked": [x for x in rows if x["distribution_state"] != "READY"],
        "rule": "Kein automatisches Update ohne eindeutigen Git-Commit, grüne Tests, lokalen Abgleich und definierten Update-Pfad.",
    }
