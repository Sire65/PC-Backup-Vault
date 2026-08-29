from __future__ import annotations

import json
from pathlib import Path


STATE_TO_DECISION = {
    'IDENTICAL': ('NO_ACTION', 'Identisch mit GitHub; keine Aktion nötig.'),
    'LOCAL_ONLY': ('RECOVERY_BRANCH_CANDIDATE', 'Nur lokal vorhanden; für einen separaten Recovery-Branch vormerken.'),
    'DIVERGENT': ('MANUAL_REVIEW', 'Lokale und GitHub-Version unterscheiden sich; niemals automatisch überschreiben.'),
    'POSSIBLE_MATCH': ('VERIFY_CONTENT', 'Nur möglicher Treffer; Inhaltsvergleich vervollständigen.'),
    'REPO_UNAVAILABLE': ('DEFER', 'Repository nicht erreichbar; später erneut read-only prüfen.'),
    'UNASSIGNED': ('ASSIGN_REPOSITORY', 'Kein Ziel-Repository sicher erkannt; zuerst Repository zuordnen.'),
}


def build_recovery_plan(compare_report: dict) -> dict:
    """Build a read-only action plan from a GitHub comparison report.

    This function never creates branches, writes files to GitHub, or modifies local sources.
    """
    items = []
    counts: dict[str, int] = {}
    for row in compare_report.get('items', []):
        state = str(row.get('state') or 'UNASSIGNED')
        decision, reason = STATE_TO_DECISION.get(state, ('MANUAL_REVIEW', 'Unbekannter Zustand; manuelle Prüfung erforderlich.'))
        planned = {
            'path': row.get('path', ''),
            'repo': row.get('repo', ''),
            'repo_path': row.get('repo_path', ''),
            'compare_state': state,
            'decision': decision,
            'reason': reason,
            'local_sha256': row.get('local_sha256', ''),
            'remote_sha256': row.get('remote_sha256', ''),
            'github_write_performed': False,
            'main_modified': False,
        }
        items.append(planned)
        counts[decision] = counts.get(decision, 0) + 1
    return {
        'schema': 'pc-backup-vault.recovery-plan.v1',
        'read_only': True,
        'github_write_performed': False,
        'main_modified': False,
        'counts': counts,
        'items': items,
    }


def export_recovery_plan(plan: dict, target: str) -> str:
    path = Path(target)
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')
    return str(path)
