from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from .scanner import cleanup_candidates, export_csv, export_json, scan


def _stamp() -> str:
    return time.strftime('%Y%m%d-%H%M%S')


def _safe_mkdir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def run_job(profile_file: str) -> dict:
    profile_path = Path(profile_file)
    profile = json.loads(profile_path.read_text(encoding='utf-8'))
    roots = [str(Path(x).expanduser()) for x in profile.get('roots', [])]
    if not roots:
        raise ValueError('Profil enthält keine Suchbereiche.')

    output_root = Path(profile.get('output_root') or (Path.home() / 'PC-Backup-Vault-Analysen'))
    _safe_mkdir(output_root)
    run_dir = output_root / f"{profile.get('name','scan')}-{_stamp()}"
    _safe_mkdir(run_dir)

    log_file = run_dir / 'job.log'
    state_file = run_dir / 'status.json'

    def write_state(status: str, **extra):
        payload = {
            'status': status,
            'profile': str(profile_path),
            'roots': roots,
            'updated': time.strftime('%Y-%m-%d %H:%M:%S'),
            **extra,
        }
        state_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')

    def progress(n: int, p: str):
        if n % 500 == 0:
            with log_file.open('a', encoding='utf-8') as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} | {n} | {p}\n")
            write_state('RUNNING', files=n, current=p)

    write_state('STARTING')
    started = time.time()
    items = scan(
        roots,
        max_hash_bytes=int(profile.get('max_hash_bytes', 64 * 1024 * 1024)),
        hash_only_interesting=bool(profile.get('hash_only_interesting', True)),
        include_hidden=bool(profile.get('include_hidden', False)),
        progress=progress,
    )
    proposals = cleanup_candidates(items)

    export_json(items, str(run_dir / 'inventory.json'))
    export_csv(items, str(run_dir / 'inventory.csv'))
    (run_dir / 'cleanup-proposals.json').write_text(
        json.dumps(proposals, ensure_ascii=False, indent=2), encoding='utf-8'
    )

    summary = {
        'status': 'SUCCESS',
        'profile': profile.get('name', 'scan'),
        'roots': roots,
        'files': len(items),
        'bytes': sum(x.size for x in items),
        'duplicates': sum(1 for x in items if x.duplicate_of),
        'review_candidates': sum(1 for x in proposals if x['proposed_action'] == 'REVIEW'),
        'quarantine_candidates': sum(1 for x in proposals if x['proposed_action'] == 'QUARANTINE'),
        'duration_seconds': round(time.time() - started, 1),
        'run_dir': str(run_dir),
        'automatic_deletion_performed': False,
        'note': 'Unbeaufsichtigte Jobs analysieren nur. Löschen/Quarantäne bleibt bewusst ein separater Freigabeschritt.',
    }
    (run_dir / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    write_state('SUCCESS', **summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description='PC Backup Vault Projekt-Finder Job Runner')
    parser.add_argument('--profile', required=True, help='Pfad zu einer .json/.kcscan Profil-Datei')
    args = parser.parse_args()
    try:
        summary = run_job(args.profile)
        print(json.dumps(summary, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(f'JOB_FAILED: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
