from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional

INTERESTING_EXTS = {
    '.zip', '.rar', '.7z', '.tar', '.gz', '.tgz',
    '.py', '.js', '.ts', '.tsx', '.jsx', '.html', '.css', '.json', '.sql',
    '.exe', '.msi', '.bat', '.cmd', '.ps1', '.md', '.txt'
}
SOURCE_EXTS = {'.py', '.js', '.ts', '.tsx', '.jsx', '.html', '.css', '.json', '.sql'}
ARCHIVE_EXTS = {'.zip', '.rar', '.7z', '.tar', '.gz', '.tgz'}
PROJECT_WORDS = (
    'kc', 'dienstplan', 'dp2', 'dp3', 'kasse', 'marktkasse', 'manager', 'verwaltung',
    'futura', 'communication', 'backup', 'vault', 'money', 'butler', 'leitstand',
    'weihnacht', 'wm-', 'wm_', 'inventar', 'bilderkasse', 'bilderrechner'
)
VERSION_RE = re.compile(r'(?<!\d)(?:v(?:ersion)?\s*)?(\d+\.\d+(?:\.\d+)?(?:[-_.][a-z0-9]+)?)', re.I)
COPY_WORDS = ('copy', 'kopie', 'alt', 'old', 'backup', 'bak', 'temp', 'tmp', 'test', 'neu', 'new', 'final')


@dataclass
class ScanItem:
    path: str
    name: str
    extension: str
    size: int
    modified: float
    modified_iso: str
    score: int
    category: str
    version_hint: str = ''
    sha256: str = ''
    duplicate_of: str = ''
    status: str = 'WHITE'
    reason: str = ''


def _iso(ts: float) -> str:
    return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ts))


def _version_hint(name: str) -> str:
    m = VERSION_RE.search(name)
    return m.group(1) if m else ''


def _score(path: Path, size: int) -> tuple[int, str, str]:
    low = str(path).lower(); ext = path.suffix.lower(); score = 0; reasons = []
    if ext in INTERESTING_EXTS: score += 20; reasons.append('relevanter Dateityp')
    if any(w in low for w in PROJECT_WORDS): score += 35; reasons.append('Projektbegriff')
    if _version_hint(path.name): score += 20; reasons.append('Versionshinweis')
    if ext in ARCHIVE_EXTS: score += 20; reasons.append('Archiv')
    if ext in SOURCE_EXTS: score += 15; reasons.append('Quelltext')
    if any(w in path.name.lower() for w in COPY_WORDS): score += 5; reasons.append('Versions-/Kopiehinweis')
    if size == 0: score -= 20; reasons.append('leer')
    return max(0, min(score, 100)), ', '.join(reasons), _version_hint(path.name)


def _category(ext: str) -> str:
    if ext in ARCHIVE_EXTS: return 'archive'
    if ext in SOURCE_EXTS: return 'source'
    if ext in {'.exe', '.msi', '.bat', '.cmd', '.ps1'}: return 'binary_or_launcher'
    return 'other'


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        while True:
            b = f.read(chunk_size)
            if not b: break
            h.update(b)
    return h.hexdigest()


def scan(roots: Iterable[str], *, max_hash_bytes: int = 64 * 1024 * 1024,
         hash_only_interesting: bool = True, include_hidden: bool = False,
         progress: Optional[Callable[[int, str], None]] = None,
         stop_requested: Optional[Callable[[], bool]] = None) -> list[ScanItem]:
    """Read-only inventory scan. Does not delete, move, rename, or alter source files."""
    items: list[ScanItem] = []; seen_hash: dict[str, str] = {}; count = 0
    for root_raw in roots:
        root = Path(root_raw).expanduser()
        if not root.exists(): continue
        for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
            if stop_requested and stop_requested(): return items
            if not include_hidden:
                dirnames[:] = [d for d in dirnames if not d.startswith('.') and d not in {'$RECYCLE.BIN', 'System Volume Information'}]
            for filename in filenames:
                if stop_requested and stop_requested(): return items
                path = Path(dirpath) / filename
                if not include_hidden and filename.startswith('.'): continue
                try: st = path.stat()
                except (OSError, PermissionError): continue
                ext = path.suffix.lower(); score, reason, version = _score(path, st.st_size)
                item = ScanItem(path=str(path), name=path.name, extension=ext, size=st.st_size,
                                modified=st.st_mtime, modified_iso=_iso(st.st_mtime), score=score,
                                category=_category(ext), version_hint=version, reason=reason)
                should_hash = st.st_size <= max_hash_bytes and (not hash_only_interesting or score >= 40 or ext in ARCHIVE_EXTS)
                if should_hash:
                    try:
                        item.sha256 = sha256_file(path)
                        if item.sha256 in seen_hash:
                            item.duplicate_of = seen_hash[item.sha256]; item.status = 'BLUE'
                            item.reason = (item.reason + ', ' if item.reason else '') + 'bit-identische Dublette'
                        else: seen_hash[item.sha256] = item.path
                    except (OSError, PermissionError): pass
                if item.status != 'BLUE': item.status = 'GREEN' if score >= 75 else 'YELLOW' if score >= 45 else 'WHITE'
                items.append(item); count += 1
                if progress and count % 100 == 0: progress(count, str(path))
    return items


def cleanup_candidates(items: Iterable[ScanItem]) -> list[dict]:
    """Generate proposals only. Never deletes anything."""
    out = []
    for i in items:
        action = 'KEEP'; confidence = 0; reason = ''
        if i.duplicate_of:
            action, confidence, reason = 'QUARANTINE', 95, f'Bit-identische Dublette von {i.duplicate_of}'
        elif i.size == 0 and i.category in {'archive', 'source'}:
            action, confidence, reason = 'REVIEW', 80, 'Leere Entwicklungsdatei'
        elif i.category == 'archive' and any(w in i.name.lower() for w in ('temp', 'tmp', 'test', 'old', 'alt', 'bak')):
            action, confidence, reason = 'REVIEW', 55, 'Archivname deutet auf Zwischen-/Altstand hin'
        out.append({**asdict(i), 'proposed_action': action, 'confidence': confidence, 'cleanup_reason': reason})
    return out


def export_json(items: Iterable[ScanItem], target: str) -> str:
    path = Path(target); path.write_text(json.dumps([asdict(x) for x in items], ensure_ascii=False, indent=2), encoding='utf-8'); return str(path)


def export_csv(items: Iterable[ScanItem], target: str) -> str:
    rows = [asdict(x) for x in items]; path = Path(target)
    with path.open('w', newline='', encoding='utf-8-sig') as f:
        if rows:
            w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    return str(path)


def quarantine(paths: Iterable[str], quarantine_root: str, *, reason: str = 'user-approved') -> list[dict]:
    """Move explicitly selected files into reversible quarantine; never permanent delete."""
    root = Path(quarantine_root); stamp = time.strftime('%Y%m%d-%H%M%S'); batch = root / stamp
    batch.mkdir(parents=True, exist_ok=True); manifest = []
    for raw in paths:
        src = Path(raw)
        if not src.exists() or src.is_dir(): continue
        before_hash = ''
        try: before_hash = sha256_file(src)
        except (OSError, PermissionError): pass
        dest = batch / src.name; n = 1
        while dest.exists(): dest = batch / f'{src.stem}__{n}{src.suffix}'; n += 1
        size = src.stat().st_size
        shutil.move(str(src), str(dest))
        manifest.append({
            'source': str(src), 'quarantine': str(dest), 'size': size,
            'sha256': before_hash, 'quarantined_at_epoch': time.time(),
            'quarantined_at': time.strftime('%Y-%m-%d %H:%M:%S'), 'reason': reason,
        })
    payload = {'schema': 'pc-backup-vault.quarantine-manifest.v2', 'batch': stamp, 'items': manifest,
               'permanent_delete_performed': False}
    (batch / 'manifest.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return manifest


def _manifest_items(payload) -> list[dict]:
    return payload.get('items', []) if isinstance(payload, dict) else payload


def restore_quarantine(manifest_file: str) -> list[dict]:
    payload = json.loads(Path(manifest_file).read_text(encoding='utf-8')); restored = []
    for row in _manifest_items(payload):
        src = Path(row['quarantine']); dest = Path(row['source'])
        if not src.exists() or dest.exists(): continue
        expected = str(row.get('sha256') or '')
        if expected:
            try:
                if sha256_file(src) != expected: continue
            except (OSError, PermissionError): continue
        dest.parent.mkdir(parents=True, exist_ok=True); shutil.move(str(src), str(dest)); restored.append({'restored': str(dest)})
    return restored


def purge_quarantine(manifest_file: str, *, min_age_days: int = 30, confirmed: bool = False, now: float | None = None) -> list[dict]:
    """Permanently delete only quarantined files after age gate and explicit confirmation."""
    if not confirmed:
        raise PermissionError('Endgültiges Löschen erfordert eine ausdrückliche Bestätigung.')
    payload = json.loads(Path(manifest_file).read_text(encoding='utf-8')); current = time.time() if now is None else now
    deleted = []
    for row in _manifest_items(payload):
        q = Path(row['quarantine']); when = float(row.get('quarantined_at_epoch') or 0)
        if not q.exists() or q.is_dir() or when <= 0: continue
        age_days = (current - when) / 86400
        if age_days < min_age_days: continue
        expected = str(row.get('sha256') or '')
        if expected:
            try:
                if sha256_file(q) != expected: continue
            except (OSError, PermissionError): continue
        q.unlink(); deleted.append({'deleted': str(q), 'age_days': round(age_days, 1)})
    return deleted
