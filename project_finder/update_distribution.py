from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable


SAFE_UPDATE_MODES = {"AUTO", "CHECK_AND_INSTALL"}
SAFE_LOCAL_STATES = {"MATCH", "GIT_NEWER"}


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
    download_url: str = ""
    rollback_available: bool = False
    current_sha: str = ""


def evaluate_target(target: UpdateTarget) -> dict:
    """Conservative update decision; READY is only an offer, never silent install permission."""
    state = "BLOCKED"; reason = "Updatefreigabe fehlt."
    if not target.head_sha: reason = "Kein eindeutiger Git-Commit vorhanden."
    elif target.test_state != "PASS": reason = "Aktueller Git-Stand ist nicht durch grüne Tests freigegeben."
    elif target.local_state in {"LOCAL_NEWER", "DIVERGED"}: reason = "Lokaler Stand muss zuerst gesichert und abgeglichen werden."
    elif target.local_state not in SAFE_LOCAL_STATES: reason = "Lokaler Stand wurde noch nicht eindeutig gegen Git abgeglichen."
    elif target.update_mode not in SAFE_UPDATE_MODES: reason = "Für dieses Programm ist noch kein sicherer Update-Pfad definiert."
    elif not target.download_url: reason = "Es fehlt eine eindeutige, versionierte Download-/Release-Quelle."
    elif target.current_sha and target.current_sha == target.head_sha:
        state = "CURRENT"; reason = "Installierter Stand entspricht bereits dem freigegebenen Git-Commit."
    else:
        state = "READY"; reason = "Getesteter Git-Stand mit lokalem Abgleich und definierter Release-Quelle."
    return {**asdict(target), "distribution_state": state, "reason": reason}


def recovery_decision(target: UpdateTarget) -> dict:
    if target.local_state == "LOCAL_NEWER": return {"state": "PROTECT_LOCAL", "reason": "Lokaler Stand ist neuer: zuerst sichern, inventarisieren und als mögliche Entwicklung schützen."}
    if target.local_state == "DIVERGED": return {"state": "COMPARE_REQUIRED", "reason": "Lokaler und Git-Stand sind auseinander gelaufen; kein Überschreiben zulässig."}
    if target.local_state == "GIT_NEWER": return {"state": "UPDATE_CANDIDATE", "reason": "Git ist neuer; Update darf nur über die Update-Sicherheitsgates angeboten werden."}
    if target.local_state == "MATCH": return {"state": "MATCH", "reason": "Lokaler und Git-Stand stimmen überein."}
    return {"state": "UNKNOWN", "reason": "Lokaler Stand ist noch nicht sicher mit Git verglichen."}


def build_update_plan(targets: Iterable[UpdateTarget]) -> dict:
    # Materialize exactly once: callers may pass generators/DB cursors/one-shot iterables.
    rows = list(targets)
    evaluated = [evaluate_target(x) for x in rows]
    recovery = [{**asdict(x), **recovery_decision(x)} for x in rows]
    return {
        "schema": "pc-backup-vault.update-plan.v2",
        "ready": [x for x in evaluated if x["distribution_state"] == "READY"],
        "current": [x for x in evaluated if x["distribution_state"] == "CURRENT"],
        "blocked": [x for x in evaluated if x["distribution_state"] == "BLOCKED"],
        "recovery": recovery,
        "safety": {"automatic_install": False, "overwrite_local_newer": False, "overwrite_diverged": False, "green_tests_required": True, "local_comparison_required": True, "versioned_download_required": True, "rollback_preferred": True},
        "rule": "Kein Update ohne eindeutigen Git-Commit, grüne Tests, lokalen Abgleich und versionierte Release-Quelle; lokale neuere/abweichende Entwicklung wird niemals überschrieben.",
    }
