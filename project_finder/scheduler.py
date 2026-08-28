from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path


@dataclass
class ScheduleSpec:
    name: str
    profile_file: str
    cadence: str = 'DAILY'  # DAILY, WEEKLY, ONCE
    start_time: str = '02:00'
    days: str = 'MON,TUE,WED,THU,FRI,SAT,SUN'
    enabled: bool = True


def save_profile(path: str, *, name: str, roots: list[str], output_root: str | None = None,
                 max_hash_bytes: int = 64 * 1024 * 1024,
                 hash_only_interesting: bool = True,
                 include_hidden: bool = False) -> str:
    payload = {
        'schema': 'pc-backup-vault.project-finder.profile.v1',
        'name': name,
        'roots': roots,
        'output_root': output_root,
        'max_hash_bytes': max_hash_bytes,
        'hash_only_interesting': hash_only_interesting,
        'include_hidden': include_hidden,
        'safety': {
            'read_only_scan': True,
            'automatic_permanent_delete': False,
            'automatic_quarantine': False,
        },
    }
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return str(p)


def _task_command(profile_file: str) -> str:
    python = Path(sys.executable)
    return f'"{python}" -m project_finder.job_runner --profile "{Path(profile_file)}"'


def create_windows_task(spec: ScheduleSpec) -> dict:
    """Create/update a Windows Task Scheduler entry using schtasks.

    Scheduled jobs are analysis-only. They never invoke quarantine or permanent deletion.
    """
    cadence = spec.cadence.upper()
    if cadence not in {'DAILY', 'WEEKLY', 'ONCE'}:
        raise ValueError('cadence muss DAILY, WEEKLY oder ONCE sein')
    task_name = f'PC Backup Vault - ProjektFinder - {spec.name}'
    cmd = ['schtasks', '/Create', '/F', '/TN', task_name, '/TR', _task_command(spec.profile_file), '/ST', spec.start_time]
    if cadence == 'DAILY':
        cmd += ['/SC', 'DAILY']
    elif cadence == 'WEEKLY':
        cmd += ['/SC', 'WEEKLY', '/D', spec.days]
    else:
        cmd += ['/SC', 'ONCE']
    proc = subprocess.run(cmd, capture_output=True, text=True, shell=False)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or 'Task Scheduler Fehler')
    if not spec.enabled:
        subprocess.run(['schtasks', '/Change', '/TN', task_name, '/DISABLE'], capture_output=True, text=True, shell=False)
    return {'task_name': task_name, 'spec': asdict(spec), 'result': proc.stdout.strip()}


def run_windows_task_now(name: str) -> dict:
    task_name = f'PC Backup Vault - ProjektFinder - {name}'
    proc = subprocess.run(['schtasks', '/Run', '/TN', task_name], capture_output=True, text=True, shell=False)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
    return {'task_name': task_name, 'started': True, 'result': proc.stdout.strip()}


def delete_windows_task(name: str) -> dict:
    task_name = f'PC Backup Vault - ProjektFinder - {name}'
    proc = subprocess.run(['schtasks', '/Delete', '/F', '/TN', task_name], capture_output=True, text=True, shell=False)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
    return {'task_name': task_name, 'deleted': True}


def query_windows_task(name: str) -> dict:
    task_name = f'PC Backup Vault - ProjektFinder - {name}'
    proc = subprocess.run(['schtasks', '/Query', '/TN', task_name, '/FO', 'LIST', '/V'], capture_output=True, text=True, shell=False)
    return {'task_name': task_name, 'exists': proc.returncode == 0, 'details': proc.stdout.strip(), 'error': proc.stderr.strip()}
