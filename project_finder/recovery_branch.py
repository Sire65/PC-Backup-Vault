from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .scanner import sha256_file

GITHUB_API = 'https://api.github.com'
SAFE_BRANCH_PREFIX = 'recovery/project-finder-'


def _request_json(url: str, *, token: str, method: str = 'GET', payload: dict | None = None):
    headers = {
        'Accept': 'application/vnd.github+json',
        'User-Agent': 'PC-Backup-Vault-Project-Finder',
        'X-GitHub-Api-Version': '2022-11-28',
    }
    if token:
        headers['Authorization'] = f'Bearer {token}'
    data = None
    if payload is not None:
        headers['Content-Type'] = 'application/json'
        data = json.dumps(payload).encode('utf-8')
    request = urllib.request.Request(url, headers=headers, data=data, method=method)
    with urllib.request.urlopen(request, timeout=20) as response:
        raw = response.read()
        return json.loads(raw.decode('utf-8')) if raw else {}


def _default_branch(repo: str, token: str) -> str:
    data = _request_json(f'{GITHUB_API}/repos/{repo}', token=token)
    return str(data.get('default_branch') or 'main')


def _branch_head_sha(repo: str, branch: str, token: str) -> str:
    encoded = urllib.parse.quote(branch, safe='')
    data = _request_json(f'{GITHUB_API}/repos/{repo}/git/ref/heads/{encoded}', token=token)
    return str((data.get('object') or {}).get('sha') or '')


def _create_branch_ref(repo: str, branch: str, sha: str, token: str) -> dict:
    return _request_json(
        f'{GITHUB_API}/repos/{repo}/git/refs',
        token=token,
        method='POST',
        payload={'ref': f'refs/heads/{branch}', 'sha': sha},
    )


def validate_recovery_preview(preview: dict) -> list[str]:
    errors: list[str] = []
    if preview.get('schema') != 'pc-backup-vault.recovery-preview.v1':
        errors.append('unsupported_preview_schema')
    if preview.get('main_modified'):
        errors.append('preview_claims_main_modified')
    for group in preview.get('groups', []):
        branch = str(group.get('proposed_branch') or '')
        if not branch.startswith(SAFE_BRANCH_PREFIX):
            errors.append(f'unsafe_branch_name:{branch}')
        if branch.lower() in {'main', 'master'}:
            errors.append(f'protected_branch_name:{branch}')
        repo = str(group.get('repo') or '')
        if not repo or '/' not in repo:
            errors.append(f'invalid_repository:{repo}')
        for row in group.get('files', []):
            source = Path(str(row.get('source_path') or ''))
            expected = str(row.get('sha256') or '')
            if not source.exists() or not source.is_file():
                errors.append(f'source_missing:{source}')
                continue
            if expected and sha256_file(source) != expected:
                errors.append(f'source_changed_since_preview:{source}')
            if row.get('blocked'):
                errors.append(f'blocked_candidate:{source}')
    return errors


def create_recovery_branches(preview: dict, *, token: str | None = None) -> dict:
    """Create empty recovery branches only; never uploads files and never touches main.

    The caller must obtain explicit user approval before invoking this function.
    """
    token = os.environ.get('GITHUB_TOKEN', '') if token is None else token
    if not token:
        raise RuntimeError('GITHUB_TOKEN fehlt. Der Token wird nur aus der Umgebungsvariable gelesen und nicht gespeichert.')

    validation_errors = validate_recovery_preview(preview)
    if validation_errors:
        raise RuntimeError('Recovery-Vorschau ist nicht mehr sicher freigabefähig: ' + '; '.join(validation_errors[:8]))

    created = []
    failed = []
    for group in preview.get('groups', []):
        repo = str(group.get('repo') or '')
        branch = str(group.get('proposed_branch') or '')
        try:
            base_branch = _default_branch(repo, token)
            base_sha = _branch_head_sha(repo, base_branch, token)
            if not base_sha:
                raise RuntimeError(f'Basis-SHA für {repo}:{base_branch} konnte nicht ermittelt werden')
            _create_branch_ref(repo, branch, base_sha, token)
            created.append({
                'repo': repo,
                'branch': branch,
                'base_branch': base_branch,
                'base_sha': base_sha,
                'files_written': 0,
                'main_modified': False,
            })
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, RuntimeError, json.JSONDecodeError) as exc:
            failed.append({'repo': repo, 'branch': branch, 'error': str(exc)})

    return {
        'schema': 'pc-backup-vault.recovery-branch-create.v1',
        'github_write_performed': bool(created),
        'branch_refs_created': len(created),
        'files_written': 0,
        'main_modified': False,
        'created': created,
        'failed': failed,
    }
