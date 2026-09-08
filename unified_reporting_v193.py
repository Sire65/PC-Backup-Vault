from __future__ import annotations

import csv
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
    parents = {str(p.parent) for p in rows}
    return {"source_label": label, "source_count": len(rows), "directory_count": len(parents)}


def target_summary(target: dict[str, Any] | None, result: dict[str, Any] | None = None) -> dict[str, str]:
    target = target or {}
    result = result or {}
    provider = str(result.get("provider") or "").upper()
    transport = str(result.get("transport") or target.get("cloud_method") or "").upper()
    name = str(target.get("name") or result.get("target_name") or "Backup-Ziel").strip()
    kind = str(target.get("kind") or "").upper()
    if provider == "STRATO_HIDRIVE" or kind == "CLOUD-SFTP":
        clean_name = name.replace("Cloud · ", "", 1).strip()
        label = clean_name if "hidrive" in clean_name.lower() else f"STRATO HiDrive · {clean_name}"
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
    out["reported_at"] = datetime.now().astimezone().isoformat(timespec="microseconds")
    return out


def report_lines(result: dict[str, Any]) -> list[str]:
    r = result
    verification = (r.get("verification") or {}).get("status", "noch nicht durchgeführt")
    selftest = (r.get("selftest") or {}).get("status", "noch nicht durchgeführt")
    return [
        "PC BACKUP VAULT – BACKUP-REPORT",
        "=" * 64,
        f"Job-ID: {r.get('job_id') or '–'}",
        f"App-Version: {r.get('app_version') or APP_VERSION}",
        f"Status: {r.get('status') or '–'}",
        f"Quelle: {r.get('source_label') or '–'}",
        f"Ziel: {r.get('target_label') or '–'}",
        f"Quelle → Ziel: {r.get('source_to_target') or '–'}",
        f"Speicherart: {r.get('backend_label') or '–'}",
        f"Transport: {r.get('transport_label') or '–'}",
        f"Plan: {r.get('plan_name') or '–'}",
        "",
        "UMFANG",
        f"Dateien: {int(r.get('files') or r.get('file_count') or 0)}",
        f"Verzeichnisse: {int(r.get('directory_count') or 0)}",
        f"Original-Datenmenge: {human_size(r.get('original_bytes'))}",
        f"Neu gespeichert/übertragen: {human_size(r.get('stored_bytes'))}",
        "",
        "ZEIT / LEISTUNG",
        f"Aktive Dauer: {float(r.get('duration_seconds') or 0):.1f} s",
        f"Ø Geschwindigkeit: {human_size(r.get('avg_speed_bps'))}/s",
        f"Transfer-Spitze: {human_size(r.get('peak_transfer_bps'))}/s",
        "",
        "VERIFIZIERUNG",
        f"Verifizierung: {verification}",
        f"Restore-Probe: {selftest}",
        "",
        f"Report erzeugt: {r.get('reported_at') or datetime.now().astimezone().isoformat(timespec='seconds')}",
    ]


def report_text(result: dict[str, Any]) -> str:
    return "\n".join(report_lines(result)) + "\n"


def reports_dir(store) -> Path:
    return Path(store.path).parent / "reports"


def persist_local_job_report(store, result: dict[str, Any], paths: Iterable[Path], target: dict[str, Any] | None = None) -> dict[str, Any]:
    """Persist a credential-free local audit record for every filesystem/HiDrive job."""
    r = enrich_result(result, paths, target)
    base = reports_dir(store)
    base.mkdir(parents=True, exist_ok=True)
    job_id = str(r.get("job_id") or "unknown")
    safe = {k: v for k, v in r.items() if k not in {"target", "cloud_account_id"}}
    (base / f"{job_id}.json").write_text(json.dumps(safe, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (base / f"{job_id}.txt").write_text(report_text(safe), encoding="utf-8")
    return r


def load_local_job_report(store, job_id: str) -> dict[str, Any] | None:
    path = reports_dir(store) / f"{str(job_id)}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def list_local_job_reports(store) -> list[dict[str, Any]]:
    base = reports_dir(store)
    if not base.exists():
        return []
    rows: list[tuple[dict[str, Any], int]] = []
    for path in base.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("job_id"):
                rows.append((data, path.stat().st_mtime_ns))
        except Exception:
            continue
    rows.sort(key=lambda item: (str(item[0].get("reported_at") or ""), item[1], str(item[0].get("job_id") or "")), reverse=True)
    return [item[0] for item in rows]


def latest_local_job_report(store) -> dict[str, Any] | None:
    rows = list_local_job_reports(store)
    return rows[0] if rows else None


def save_report_txt(result: dict[str, Any], path: str | Path):
    Path(path).write_text(report_text(result), encoding="utf-8")


def save_report_csv(result: dict[str, Any], path: str | Path):
    fields = {
        "job_id": result.get("job_id"),
        "app_version": result.get("app_version"),
        "status": result.get("status"),
        "quelle": result.get("source_label"),
        "ziel": result.get("target_label"),
        "quelle_zu_ziel": result.get("source_to_target"),
        "speicherart": result.get("backend_label"),
        "transport": result.get("transport_label"),
        "dateien": result.get("files") or result.get("file_count"),
        "verzeichnisse": result.get("directory_count"),
        "original_bytes": result.get("original_bytes"),
        "stored_bytes": result.get("stored_bytes"),
        "duration_seconds": result.get("duration_seconds"),
        "avg_speed_bps": result.get("avg_speed_bps"),
        "peak_transfer_bps": result.get("peak_transfer_bps"),
        "reported_at": result.get("reported_at"),
    }
    with Path(path).open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh, delimiter=";")
        writer.writerow(["Feld", "Wert"])
        for key, value in fields.items():
            writer.writerow([key, "" if value is None else str(value)])
