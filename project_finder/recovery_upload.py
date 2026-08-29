from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .git_handoff import exclusion_reason, secret_content_reason
from .recovery_branch import GITHUB_API, SAFE_BRANCH_PREFIX
from .scanner import sha256_file


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
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read()
        return json.loads(raw.decode('utf-8')) if raw else {}


def _safe_repo_path(repo_path: str) -> bool:
    path = repo_path.replace('\\', '/').strip('/')
    if not path or path.startswith('.') and path.split('/', 1)[0] == '.git':
        return False
    parts = [p for p in path.split('/') if p]
    return bool(parts) and all(p not in {'.', '..'} for p in parts)


def build_recovery_upload_plan(preview: dict, branch_result: dict) -> dict:
    """Build a read-only upload plan from a validated preview and branch-create result."""
    created = {
        (str(row.get('repo') or ''), str(row.get('branch') or ''))
        for row in branch_result.get('created', [])
    }
    ready = []
    blocked = []

    for group in preview.get('groups', []):
        repo = str(group.get('repo') or '')
        branch = str(group.get('proposed_branch') or '')
        branch_exists_from_result = (repo, branch) in created
        for row in group.get('files', []):
            source = Path(str(row.get('source_path') or ''))
            repo_path = str(row.get('repo_path') or '').replace('\\', '/').lstrip('/')
            expected_sha = str(row.get('sha256') or '')
            reasons = []

            if not branch.startswith(SAFE_BRANCH_PREFIX) or branch.lower() in {'main', 'master'}:
                reasons.append('unsafe_branch')
            if not branch_exists_from_result:
                reasons.append('branch_not_confirmed_created')
            if not repo or '/' not in repo:
                reasons.append('invalid_repository')
            if not _safe_repo_path(repo_path):
                reasons.append('unsafe_repository_path')
            if not source.exists() or not source.is_file():
                reasons.append('source_missing')
            else:
                path_reason = exclusion_reason(source)
                if path_reason:
                    reasons.append(path_reason)
                content_reason = secret_content_reason(source)
                if content_reason:
                    reasons.append(content_reason)
                current_sha = sha256_file(source)
                if not expected_sha or current_sha != expected_sha:
                    reasons.append('source_changed_since_preview')

            entry = {
                'source_path': str(source),
                'repo': repo,
                'branch': branch,
                'repo_path': repo_path,
                'sha256': expected_sha,
                'operation': 'CREATE_NEW_FILE_ONLY',
                'overwrite_allowed': False,
                'main_modified': False,
            }
            if reasons:
                blocked.append({**entry, 'blocked': True, 'block_reasons': reasons})
            else:
                ready.append({**entry, 'blocked': False, 'block_reasons': []})

    return {
        'schema': 'pc-backup-vault.recovery-upload-plan.v1',
        'read_only': True,
        'overwrite_allowed': False,
        'main_modified': False,
        'ready_count': len(ready),
        'blocked_count': len(blocked),
        'ready': ready,
        'blocked': blocked,
    }


def _target_exists(repo: str, branch: str, repo_path: str, token: str) -> bool:
    encoded_path = urllib.parse.quote(repo_path, safe='/')
    encoded_ref = urllib.parse.quote(branch, safe='')
    url = f'{GITHUB_API}/repos/{repo}/contents/{encoded_path}?ref={encoded_ref}'
    try:
        _request_json(url, token=token)
        return True
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False
        raise


def _create_file(repo: str, branch: str, repo_path: str, source: Path, token: str) -> dict:
    encoded_path = urllib.parse.quote(repo_path, safe='/')
    content = base64.b64encode(source.read_bytes()).decode('ascii')
    payload = {
        'message': f'Recovery import: {repo_path}',
        'content': content,
        'branch': branch,
    }
    return _request_json(
        f'{GITHUB_API}/repos/{repo}/contents/{encoded_path}',
        token=token,
        method='PUT',
        payload=payload,
    )


def upload_recovery_files(plan: dict, *, approved: bool = False, token: str | None = None) -> dict:
    """Upload only NEW files to existing recovery branches after explicit approval.

    Never updates existing files and never targets main/master.
    """
    if not approved:
        raise PermissionError('Recovery-Datei-Upload erfordert eine ausdrückliche Freigabe.')
    if plan.get('schema') != 'pc-backup-vault.recovery-upload-plan.v1':
        raise RuntimeError('Ungültiger Recovery-Upload-Plan.')
    if plan.get('blocked_count'):
        raise RuntimeError('Recovery-Upload-Plan enthält blockierte Dateien und ist nicht freigabefähig.')

    token = os.environ.get('GITHUB_TOKEN', '') if token is None else token
    if not token:
        raise RuntimeError('GITHUB_TOKEN fehlt. Der Token wird nur aus der Umgebungsvariable gelesen und nicht gespeichert.')

    uploaded = []
    failed = []
    for row in plan.get('ready', []):
        repo = str(row.get('repo') or '')
        branch = str(row.get('branch') or '')
        repo_path = str(row.get('repo_path') or '')
        source = Path(str(row.get('source_path') or ''))
        expected_sha = str(row.get('sha256') or '')
        try:
            if not branch.startswith(SAFE_BRANCH_PREFIX) or branch.lower() in {'main', 'master'}:
                raise RuntimeError('unsafe_branch')
            if not _safe_repo_path(repo_path):
                raise RuntimeError('unsafe_repository_path')
            if not source.exists() or not source.is_file():
                raise RuntimeError('source_missing')
            if exclusion_reason(source) or secret_content_reason(source):
                raise RuntimeError('source_blocked_by_secret_or_runtime_filter')
            if not expected_sha or sha256_file(source) != expected_sha:
                raise RuntimeError('source_changed_since_plan')
            if _target_exists(repo, branch, repo_path, token):
                raise RuntimeError('target_already_exists_no_overwrite')
            response = _create_file(repo, branch, repo_path, source, token)
            uploaded.append({
                'repo': repo,
                'branch': branch,
                'repo_path': repo_path,
                'source_path': str(source),
                'sha256': expected_sha,
                'commit_sha': str((response.get('commit') or {}).get('sha') or ''),
                'main_modified': False,
            })
        except (OSError, urllib.error.HTTPError, urllib.error.URLError, TimeoutError, RuntimeError, json.JSONDecodeError) as exc:
            failed.append({'repo': repo, 'branch': branch, 'repo_path': repo_path, 'error': str(exc)})

    return {
        'schema': 'pc-backup-vault.recovery-upload-result.v1',
        'github_write_performed': bool(uploaded),
        'uploaded_count': len(uploaded),
        'overwrite_performed': False,
        'main_modified': False,
        'uploaded': uploaded,
        'failed': failed,
    }
