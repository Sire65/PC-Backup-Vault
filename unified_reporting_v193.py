from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from config_store import APP_VERSION


def human_size(n: int | float | None) -> str:
    units = ("B", "KB", "MB", "GB", "TB")
    x = float(n or 0)
    for unit in units:
        if x < 1024 or unit == units[-1]:
            return f"{x:.1f} {unit}"
        x /= 1024


def source_summary(paths: Iterable[Path]) -> dict[str, Any]:
    rows = [Path(p) for p in paths]
    names = [p.name or str(p) for p in rows]
    if not names:
        label = "–"
    elif len(names) == 1:
        label = names[0]
    elif len(names) <= 3:
        label = ", ".join(names)
    else:
        label = f"{', '.join(names[:3])} + {len(names)-3} weitere"
    return {"source_label": label, "source_count": len(rows)}


def target_summary(target: dict[str, Any] | None, result: dict[str, Any] | None = None) -> dict[str, str]:
    target = target or {}
    result = result or {}
    provider = str(result.get("provider") or "").upper()
    transport = str(result.get("transport") or target.get("cloud_method") or "").upper()
    name = str(target.get("name") or result.get("target_name") or "Backup-Ziel").strip()
    kind = str(target.get("kind") or "").upper()
    if provider == "STRATO_HIDRIVE" or kind == "CLOUD-SFTP":
        label = name if "hidrive" in name.lower() else f"STRATO HiDrive · {name}"
        backend = "STRATO HiDrive"
    elif kind == "NAS":
        label, backend = name, "NAS"
    elif result.get("payload_target") == "B2":
        label, backend = "Backblaze B2 + Neon-Core", "Backblaze B2"
    else:
        label, backend = name, "Dateispeicher"
    return {"target_label": label, "backend_label": backend, "transport_label": transport or "Dateisystem"}


def enrich_result(result: dict[str, Any], paths: Iterable[Path], target: dict[str, Any] | None = None) -> dict[str, Any]:
    out = dict(result or {})
    out.update(source_summary(paths))
    out.update(target_summary(target, out))
    out["app_version"] = out.get("app_version") or APP_VERSION
    out["source_to_target"] = f"{out['source_label']} → {out['target_label']}"
    out["reported_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    return out


def report_lines(result: dict[str, Any]) -> list[str]:
    r = result
    return [
        "PC BACKUP VAULT – JOB-REPORT",
        "=" * 64,
        f"Job-ID: {r.get('job_id') or '–'}",
        f"App-Version: {r.get('app_version') or APP_VERSION}",
        f"Status: {r.get('status') or '–'}",
        f"Quelle: {r.get('source_label') or '–'}",
        f"Ziel: {r.get('target_label') or '–'}",
        f"Quelle → Ziel: {r.get('source_to_target') or '–'}",
        f"Speicherart: {r.get('backend_label') or '–'}",
        f"Transport: {r.get('transport_label') or '–'}",
        f"Dateien: {int(r.get('files') or r.get('file_count') or 0)}",
        f"Original-Datenmenge: {human_size(r.get('original_bytes'))}",
        f"Neu gespeichert/übertragen: {human_size(r.get('stored_bytes'))}",
        f"Ø Geschwindigkeit: {human_size(r.get('avg_speed_bps'))}/s",
        f"Transfer-Spitze: {human_size(r.get('peak_transfer_bps'))}/s",
        f"Verifizierung: {(r.get('verification') or {}).get('status', 'noch nicht durchgeführt')}",
        f"Restore-Probe: {(r.get('selftest') or {}).get('status', 'noch nicht durchgeführt')}",
        f"Report erzeugt: {r.get('reported_at') or datetime.now().astimezone().isoformat(timespec='seconds')}",
    ]


def persist_local_job_report(store, result: dict[str, Any], paths: Iterable[Path], target: dict[str, Any] | None = None) -> dict[str, Any]:
    """Persist a credential-free local audit record for every filesystem/HiDrive job."""
    r = enrich_result(result, paths, target)
    base = Path(store.path).parent / "reports"
    base.mkdir(parents=True, exist_ok=True)
    job_id = str(r.get("job_id") or "unknown")
    safe = {k: v for k, v in r.items() if k not in {"target", "cloud_account_id"}}
    (base / f"{job_id}.json").write_text(json.dumps(safe, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (base / f"{job_id}.txt").write_text("\n".join(report_lines(safe)) + "\n", encoding="utf-8")
    return r
