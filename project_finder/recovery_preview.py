from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Iterable

from .git_handoff import exclusion_reason
from .recovery_decision import build_recovery_plan
from .scanner import ScanItem, sha256_file


def build_recovery_preview(items: Iterable[ScanItem], compare_report: dict) -> dict:
    """Prepare a branch-import preview without creating a branch or writing to GitHub."""
    item_by_path = {str(i.path): i for i in items}
    plan = build_recovery_plan(compare_report)
    candidates = []
    blocked = []
    seen_targets: dict[tuple[str, str], str] = {}

    for row in plan.get('items', []):
        if row.get('decision') != 'RECOVERY_BRANCH_CANDIDATE':
            continue
        source_path = str(row.get('path') or '')
        repo = str(row.get('repo') or '')
        repo_path = str(row.get('repo_path') or '')
        item = item_by_path.get(source_path)
        reasons = []
        src = Path(source_path)

        if item is None:
            reasons.append('not_in_current_inventory')
        if not repo:
            reasons.append('repository_missing')
        if not repo_path:
            reasons.append('repository_path_missing')
        if exclusion_reason(src):
            reasons.append(exclusion_reason(src))
        if not src.exists() or not src.is_file():
            reasons.append('source_missing')

        current_sha = ''
        if src.exists() and src.is_file():
            current_sha = sha256_file(src)
            compared_sha = str(row.get('local_sha256') or '')
            if compared_sha and current_sha != compared_sha:
                reasons.append('source_changed_since_compare')

        target_key = (repo.lower(), repo_path.lower())
        if repo and repo_path:
            previous = seen_targets.get(target_key)
            if previous and previous != source_path:
                reasons.append('target_path_collision')
            else:
                seen_targets[target_key] = source_path

        entry = {
            'source_path': source_path,
            'repo': repo,
            'repo_path': repo_path,
            'sha256': current_sha,
            'branch_action': 'ADD_LOCAL_ONLY_FILE',
            'target_branch': '',
            'main_modified': False,
            'github_write_performed': False,
        }
        if reasons:
            blocked.append({**entry, 'blocked': True, 'block_reasons': reasons})
        else:
            candidates.append({**entry, 'blocked': False, 'block_reasons': []})

    by_repo: dict[str, list[dict]] = {}
    for row in candidates:
        by_repo.setdefault(row['repo'], []).append(row)

    groups = []
    stamp = time.strftime('%Y%m%d-%H%M%S')
    for repo in sorted(by_repo):
        safe_repo = repo.split('/', 1)[-1].lower().replace('_', '-').replace(' ', '-')
        branch = f'recovery/project-finder-{safe_repo}-{stamp}'
        rows = sorted(by_repo[repo], key=lambda x: x['repo_path'].lower())
        for row in rows:
            row['target_branch'] = branch
        groups.append({'repo': repo, 'proposed_branch': branch, 'file_count': len(rows), 'files': rows})

    return {
        'schema': 'pc-backup-vault.recovery-preview.v1',
        'read_only': True,
        'branch_created': False,
        'github_write_performed': False,
        'main_modified': False,
        'candidate_count': len(candidates),
        'blocked_count': len(blocked),
        'groups': groups,
        'blocked': blocked,
    }


def export_recovery_preview(preview: dict, target: str) -> str:
    path = Path(target)
    path.write_text(json.dumps(preview, ensure_ascii=False, indent=2), encoding='utf-8')
    return str(path)
