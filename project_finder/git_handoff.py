from __future__ import annotations

import hashlib
import json
import re
import time
import zipfile
from pathlib import Path
from typing import Iterable

from project_finder.decision_engine import classify_inventory
from project_finder.scanner import DEFAULT_EXCLUDED_DIRS, ScanItem, sha256_file

SECRET_NAMES = {'.env', '.env.local', '.env.production', '.env.development', 'credentials.json', 'secrets.json', 'service-account.json', 'id_rsa', 'id_ed25519'}
SECRET_SUFFIXES = {'.pem', '.key', '.p12', '.pfx', '.jks', '.keystore'}
SECRET_RE = re.compile(r'(secret|token|password|passwd|api[_-]?key|private[_-]?key|service[_-]?account)', re.I)
PRIVATE_KEY_RE = re.compile(r'-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----')
TOKEN_PATTERNS = (
    re.compile(r'\bghp_[A-Za-z0-9]{20,}\b'),
    re.compile(r'\bgithub_pat_[A-Za-z0-9_]{20,}\b'),
    re.compile(r'\bsb_secret_[A-Za-z0-9._-]{16,}\b'),
    re.compile(r'\bAKIA[0-9A-Z]{16}\b'),
    re.compile(r'\bsk_(?:live|test)_[A-Za-z0-9]{16,}\b'),
)
SECRET_ASSIGNMENT_RE = re.compile(
    r'(?im)^\s*(?:export\s+)?(?:SUPABASE_SERVICE_ROLE_KEY|SERVICE_ROLE_KEY|DATABASE_URL|NEON_DATABASE_URL|B2_APPLICATION_KEY|CLOUDFLARE_API_TOKEN|VAPID_PRIVATE_KEY|PRIVATE_KEY)\s*=\s*["\']?([^\s"\']{16,})'
)
TEXT_SCAN_SUFFIXES = {'.py', '.js', '.jsx', '.ts', '.tsx', '.json', '.toml', '.yaml', '.yml', '.ini', '.cfg', '.conf', '.txt', '.md', '.sql', '.ps1', '.bat', '.cmd', '.sh'}
REPO_HINTS = (
    (('dp2', 'dienstplan'), 'Sire65/Dienstplan'),
    (('pc-backup-vault', 'backup vault'), 'Sire65/PC-Backup-Vault'),
    (('bilderkasse', 'marktkasse', 'kc marktkasse'), 'Sire65/Kasse'),
    (('bilderrechner', 'kc-bilderrechner'), 'Sire65/KC-Bilderrechner'),
)


def _parts(path: Path) -> list[str]:
    return [p.lower() for p in path.parts]


def exclusion_reason(path: Path) -> str:
    parts = _parts(path)
    if any(p in {x.lower() for x in DEFAULT_EXCLUDED_DIRS} for p in parts):
        return 'generated_or_vendor_tree'
    low = path.name.lower()
    if low in SECRET_NAMES or path.suffix.lower() in SECRET_SUFFIXES or SECRET_RE.search(low):
        return 'possible_secret'
    if '.git' in parts:
        return 'git_metadata'
    return ''


def secret_content_reason(path: Path) -> str:
    """Return a high-confidence secret-content reason without exposing the secret value."""
    try:
        if not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
            return ''
    except OSError:
        return ''
    if path.suffix.lower() not in TEXT_SCAN_SUFFIXES and path.name.lower() not in {'dockerfile', 'makefile'}:
        return ''
    try:
        text = path.read_text(encoding='utf-8', errors='ignore')
    except OSError:
        return ''
    if PRIVATE_KEY_RE.search(text):
        return 'secret_content'
    if any(pattern.search(text) for pattern in TOKEN_PATTERNS):
        return 'secret_content'
    if SECRET_ASSIGNMENT_RE.search(text):
        return 'secret_content'
    return ''


def guess_repo(path: Path) -> tuple[str, int]:
    low = str(path).lower().replace('\\', '/')
    for words, repo in REPO_HINTS:
        if any(w in low for w in words):
            return repo, 90
    return '', 0


def create_git_handoff(items: Iterable[ScanItem], target_zip: str) -> dict:
    target = Path(target_zip)
    target.parent.mkdir(parents=True, exist_ok=True)
    items = list(items)
    decisions = {row['path']: row for row in classify_inventory(items)}
    rows = []
    excluded = []
    seen = set()
    with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for item in items:
            src = Path(item.path)
            decision_row = decisions.get(item.path, {})
            git_action = decision_row.get('git_action', 'NO')
            reason = exclusion_reason(src)
            if reason:
                excluded.append({'source_path': str(src), 'reason': reason})
                continue
            if git_action not in {'TO_GIT', 'REVIEW'}:
                excluded.append({'source_path': str(src), 'reason': f'git_action_{git_action.lower()}'})
                continue
            if item.duplicate_of:
                excluded.append({'source_path': str(src), 'reason': 'duplicate_content'})
                continue
            if item.category not in {'source', 'document', 'image_asset', 'binary_or_launcher'}:
                excluded.append({'source_path': str(src), 'reason': 'unsupported_category'})
                continue
            if not src.exists() or not src.is_file():
                excluded.append({'source_path': str(src), 'reason': 'missing'})
                continue
            content_reason = secret_content_reason(src)
            if content_reason:
                excluded.append({'source_path': str(src), 'reason': content_reason})
                continue
            digest = sha256_file(src)
            key = (digest, src.name.lower())
            if key in seen:
                excluded.append({'source_path': str(src), 'reason': 'duplicate_content'})
                continue
            seen.add(key)
            repo, confidence = guess_repo(src)
            project = repo.split('/', 1)[-1] if repo else 'UNASSIGNED'
            safe_name = hashlib.sha256(str(src).encode('utf-8')).hexdigest()[:12] + '_' + src.name
            archive_path = f'files/{project}/{safe_name}'
            z.write(src, archive_path)
            rows.append({
                'source_path': str(src), 'archive_path': archive_path, 'sha256': digest,
                'size': src.stat().st_size, 'category': item.category,
                'scanner_status': item.status, 'git_action': git_action,
                'inventory_action': decision_row.get('inventory_action', ''),
                'decision_confidence': decision_row.get('confidence', 0),
                'suggested_repo': repo, 'repo_confidence': confidence,
                'decision': 'REVIEW' if not repo or git_action == 'REVIEW' else 'COMPARE_WITH_GITHUB',
            })
        manifest = {
            'schema': 'pc-backup-vault.git-handoff.v2',
            'created_at': time.strftime('%Y-%m-%d %H:%M:%S'),
            'safety': {
                'source_modified': False, 'secrets_excluded': True,
                'secret_content_scanned': True, 'generated_trees_excluded': True,
                'github_write_performed': False,
            },
            'items': rows, 'excluded': excluded,
        }
        z.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
        z.writestr('README.txt', 'PC Backup Vault - Git-Uebergabepaket\n\nDieses Paket schreibt nichts nach GitHub. Dateien muessen anhand manifest.json mit dem Ziel-Repository verglichen werden. Dateinamen- und Inhaltspruefung blockieren hochwahrscheinliche Secrets. Generierte Laufzeit-/Build-Verzeichnisse und Dubletten werden ausgeschlossen. Nie blind main ueberschreiben.\n')
    return {'zip': str(target), 'included': len(rows), 'excluded': len(excluded), 'manifest': manifest}
