from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path
from typing import Iterable

from .scanner import ARCHIVE_EXTS, SOURCE_EXTS, ScanItem

IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.svg', '.ico'}
DOC_EXTS = {'.md', '.txt', '.pdf', '.docx', '.xlsx', '.pptx', '.csv'}
SECRET_NAMES = {
    '.env', '.env.local', '.env.production', 'credentials.json', 'secrets.json',
    'service-account.json', 'id_rsa', 'id_ed25519',
}
SECRET_FRAGMENTS = ('secret', 'credential', 'private_key', 'apikey', 'api_key', 'password', 'token')
TEMP_DIRS = {'tmp', 'temp', 'cache', '__pycache__', 'node_modules', '.venv', 'venv', 'dist', 'build'}
PROJECT_MARKERS = {
    'pyproject.toml', 'requirements.txt', 'package.json', 'package-lock.json',
    'vite.config.js', 'vite.config.ts', 'netlify.toml', 'vercel.json', 'schema.sql',
    'dockerfile', 'docker-compose.yml', '.gitignore',
}


def _parts_lower(path: str) -> list[str]:
    normalized = str(path).replace('\\', '/')
    return [part.lower() for part in normalized.split('/') if part]


def _is_secret(item: ScanItem) -> bool:
    name = item.name.lower()
    if name in SECRET_NAMES:
        return True
    return any(fragment in name for fragment in SECRET_FRAGMENTS)


def _is_temp_path(item: ScanItem) -> bool:
    return any(part in TEMP_DIRS for part in _parts_lower(item.path))


def _looks_project_material(item: ScanItem) -> bool:
    ext = item.extension.lower()
    if item.score >= 45:
        return True
    if ext in SOURCE_EXTS or ext in IMAGE_EXTS:
        parts = _parts_lower(item.path)
        return any(p in {'src', 'app', 'apps', 'assets', 'public', 'static', 'pos', 'pc-manager', 'tests'} for p in parts)
    return item.name.lower() in PROJECT_MARKERS


def classify_item(item: ScanItem) -> dict:
    """Conservative production recommendation. It never changes a file or Git repository."""
    base = asdict(item)

    if item.duplicate_of:
        return {**base, 'inventory_action': 'QUARANTINE_CANDIDATE', 'git_action': 'NO',
                'confidence': 98, 'decision_reason': f'Bit-identische SHA-256-Dublette von {item.duplicate_of}'}

    if _is_secret(item):
        return {**base, 'inventory_action': 'KEEP_LOCAL', 'git_action': 'NEVER',
                'confidence': 99, 'decision_reason': 'Mögliche Zugangsdaten/Secrets: niemals automatisch nach Git'}

    if item.size == 0:
        return {**base, 'inventory_action': 'REVIEW', 'git_action': 'NO',
                'confidence': 90, 'decision_reason': 'Leere Datei: vor Verwendung oder Entfernung prüfen'}

    if _is_temp_path(item):
        return {**base, 'inventory_action': 'REVIEW', 'git_action': 'NO',
                'confidence': 80, 'decision_reason': 'Datei liegt in Build-/Cache-/Temp-Bereich'}

    ext = item.extension.lower()
    project_material = _looks_project_material(item)

    if ext in ARCHIVE_EXTS:
        return {**base, 'inventory_action': 'KEEP_LOCAL', 'git_action': 'REVIEW',
                'confidence': 80, 'decision_reason': 'Archiv/Buildstand: lokal behalten; nur bewusst als Release-Artefakt nach Git'}

    if ext in SOURCE_EXTS or item.name.lower() in PROJECT_MARKERS:
        if project_material:
            return {**base, 'inventory_action': 'KEEP', 'git_action': 'TO_GIT',
                    'confidence': 90, 'decision_reason': 'Projektquelltext/-konfiguration: Git-Kandidat; gegen führenden Stand vergleichen'}

    if ext in IMAGE_EXTS and project_material:
        return {**base, 'inventory_action': 'KEEP', 'git_action': 'TO_GIT',
                'confidence': 85, 'decision_reason': 'Projekt-Asset/Bild: Git-Kandidat, sofern produktiv genutzt und nicht bereits identisch vorhanden'}

    if ext in DOC_EXTS and project_material:
        return {**base, 'inventory_action': 'KEEP', 'git_action': 'REVIEW',
                'confidence': 70, 'decision_reason': 'Projektdokumentation: auf Aktualität und Repository-Zugehörigkeit prüfen'}

    return {**base, 'inventory_action': 'KEEP_LOCAL', 'git_action': 'NO',
            'confidence': 65, 'decision_reason': 'Kein belastbarer Git- oder Löschhinweis; lokal behalten'}


def classify_inventory(items: Iterable[ScanItem]) -> list[dict]:
    return [classify_item(item) for item in items]


def inventory_summary(items: Iterable[ScanItem]) -> dict:
    rows = classify_inventory(items)
    counts = {
        'files': len(rows), 'to_git': 0, 'git_review': 0, 'keep_local': 0,
        'review': 0, 'quarantine_candidates': 0, 'never_git': 0,
    }
    sizes = {'total': 0, 'quarantine_candidates': 0}
    for row in rows:
        sizes['total'] += int(row.get('size') or 0)
        if row['git_action'] == 'TO_GIT': counts['to_git'] += 1
        if row['git_action'] == 'REVIEW': counts['git_review'] += 1
        if row['git_action'] == 'NEVER': counts['never_git'] += 1
        if row['inventory_action'] == 'KEEP_LOCAL': counts['keep_local'] += 1
        if row['inventory_action'] == 'REVIEW': counts['review'] += 1
        if row['inventory_action'] == 'QUARANTINE_CANDIDATE':
            counts['quarantine_candidates'] += 1
            sizes['quarantine_candidates'] += int(row.get('size') or 0)
    return {'counts': counts, 'sizes': sizes, 'rows': rows}


def export_inventory_json(items: Iterable[ScanItem], target: str) -> str:
    payload = inventory_summary(items)
    path = Path(target)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return str(path)


def export_inventory_csv(items: Iterable[ScanItem], target: str) -> str:
    rows = classify_inventory(items)
    path = Path(target)
    with path.open('w', newline='', encoding='utf-8-sig') as f:
        if rows:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
    return str(path)
