from __future__ import annotations

import base64
import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Iterable

from project_finder.decision_engine import classify_inventory
from project_finder.git_handoff import exclusion_reason, guess_repo
from project_finder.scanner import ScanItem, sha256_file

GITHUB_API = 'https://api.github.com'


def _request_json(url: str, token: str = ''):
    headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'PC-Backup-Vault-Project-Finder'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    req = urllib.request.Request(url, headers=headers, method='GET')
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode('utf-8'))


def fetch_default_branch(repo: str, token: str = '') -> str:
    data = _request_json(f'{GITHUB_API}/repos/{repo}', token)
    return str(data.get('default_branch') or 'main')


def fetch_repo_tree(repo: str, ref: str = '', token: str = '') -> dict[str, dict]:
    branch = ref or fetch_default_branch(repo, token)
    encoded_ref = urllib.parse.quote(branch, safe='')
    data = _request_json(f'{GITHUB_API}/repos/{repo}/git/trees/{encoded_ref}?recursive=1', token)
    index = {}
    for row in data.get('tree', []):
        if row.get('type') != 'blob':
            continue
        index[str(row.get('path') or '')] = {
            'blob_sha': str(row.get('sha') or ''),
            'size': int(row.get('size') or 0),
            'repo': repo,
            'ref': branch,
        }
    return index


def fetch_blob_sha256(repo: str, blob_sha: str, token: str = '') -> str:
    data = _request_json(f'{GITHUB_API}/repos/{repo}/git/blobs/{blob_sha}', token)
    if str(data.get('encoding') or '').lower() != 'base64':
        return ''
    raw = base64.b64decode(str(data.get('content') or '').replace('\n', ''))
    return hashlib.sha256(raw).hexdigest()


def candidate_repo_path(local_path: Path, repo: str) -> str:
    low_parts = [p.lower() for p in local_path.parts]
    repo_name = repo.split('/', 1)[-1].lower()
    aliases = {
        'dienstplan': {'dienstplan', 'dp2', 'kc dp2'},
        'pc-backup-vault': {'pc-backup-vault', 'pc backup vault'},
        'kasse': {'kasse', 'bilderkasse', 'marktkasse', 'kc marktkasse'},
        'kc-bilderrechner': {'kc-bilderrechner', 'bilderrechner', 'kc bilderrechner'},
    }.get(repo_name, {repo_name})
    start = None
    for i, part in enumerate(low_parts):
        if part in aliases:
            start = i + 1
    if start is not None and start < len(local_path.parts):
        return '/'.join(local_path.parts[start:])
    return local_path.name


def compare_item(item: ScanItem, repo_index: dict[str, dict], repo: str, *, token: str = '', verify_content: bool = True) -> dict:
    local = Path(item.path)
    repo_path = candidate_repo_path(local, repo)
    remote = repo_index.get(repo_path)
    local_hash = item.sha256 or (sha256_file(local) if local.exists() and local.is_file() else '')
    if remote is None:
        return {
            'path': str(local), 'repo': repo, 'repo_path': repo_path, 'state': 'LOCAL_ONLY',
            'local_sha256': local_hash, 'remote_sha256': '', 'reason': 'Pfad im GitHub-Repository nicht vorhanden',
        }
    remote_hash = ''
    if verify_content and remote.get('blob_sha'):
        try:
            remote_hash = fetch_blob_sha256(repo, remote['blob_sha'], token)
        except Exception:
            remote_hash = ''
    if local_hash and remote_hash:
        state = 'IDENTICAL' if local_hash == remote_hash else 'DIVERGENT'
        reason = 'SHA-256 identisch' if state == 'IDENTICAL' else 'Gleicher Pfad, unterschiedlicher Inhalt'
    else:
        same_size = int(remote.get('size') or -1) == int(item.size)
        state = 'POSSIBLE_MATCH' if same_size else 'DIVERGENT'
        reason = 'Inhalts-Hash nicht verfügbar; Dateigröße stimmt überein' if same_size else 'Pfad vorhanden, Größe/Inhalt abweichend'
    return {
        'path': str(local), 'repo': repo, 'repo_path': repo_path, 'state': state,
        'local_sha256': local_hash, 'remote_sha256': remote_hash, 'reason': reason,
    }


def _safe_compare_candidates(items: list[ScanItem]) -> tuple[list[ScanItem], list[dict]]:
    decisions = {row['path']: row for row in classify_inventory(items)}
    accepted: list[ScanItem] = []
    excluded: list[dict] = []
    for item in items:
        row = decisions.get(item.path, {})
        reason = exclusion_reason(Path(item.path))
        if item.duplicate_of:
            excluded.append({'path': item.path, 'reason': 'duplicate'})
            continue
        if reason:
            excluded.append({'path': item.path, 'reason': reason})
            continue
        git_action = str(row.get('git_action') or 'NO')
        if git_action not in {'TO_GIT', 'REVIEW'}:
            excluded.append({'path': item.path, 'reason': f'git_action_{git_action.lower()}'})
            continue
        accepted.append(item)
    return accepted, excluded


def compare_inventory(items: Iterable[ScanItem], *, token: str | None = None, verify_content: bool = True) -> dict:
    token = os.environ.get('GITHUB_TOKEN', '') if token is None else token
    source_items = list(items)
    candidates, excluded = _safe_compare_candidates(source_items)
    grouped: dict[str, list[ScanItem]] = {}
    unassigned = []
    for item in candidates:
        repo, confidence = guess_repo(Path(item.path))
        if not repo:
            unassigned.append({
                'path': item.path, 'state': 'UNASSIGNED',
                'reason': 'Kein Ziel-Repository sicher erkannt', 'repo_confidence': confidence,
            })
            continue
        grouped.setdefault(repo, []).append(item)

    results = []
    repo_errors = []
    for repo, repo_items in grouped.items():
        try:
            index = fetch_repo_tree(repo, token=token)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
            repo_errors.append({'repo': repo, 'error': str(exc)})
            for item in repo_items:
                results.append({
                    'path': item.path, 'repo': repo,
                    'repo_path': candidate_repo_path(Path(item.path), repo),
                    'state': 'REPO_UNAVAILABLE', 'reason': str(exc),
                    'local_sha256': item.sha256, 'remote_sha256': '',
                })
            continue
        for item in repo_items:
            results.append(compare_item(item, index, repo, token=token, verify_content=verify_content))

    results.extend(unassigned)
    counts: dict[str, int] = {}
    for row in results:
        counts[row['state']] = counts.get(row['state'], 0) + 1

    excluded_counts: dict[str, int] = {}
    for row in excluded:
        reason = row['reason']
        excluded_counts[reason] = excluded_counts.get(reason, 0) + 1

    return {
        'schema': 'pc-backup-vault.github-compare.v2',
        'read_only': True,
        'candidate_count': len(candidates),
        'excluded_count': len(excluded),
        'excluded_counts': excluded_counts,
        'counts': counts,
        'repo_errors': repo_errors,
        'items': results,
    }


def export_compare_report(report: dict, target: str) -> str:
    path = Path(target)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return str(path)
