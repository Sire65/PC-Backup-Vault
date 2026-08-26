from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg
from status_bus import activity

from crypto_box import decrypt_text


def human_size(n: int | float | None) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    x = float(n or 0)
    for u in units:
        if x < 1024 or u == units[-1]:
            return f"{x:.1f} {u}"
        x /= 1024


def fmt_duration(seconds: float | None) -> str:
    s = int(max(0, float(seconds or 0)))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"


def _mode_label(code: str | None) -> str:
    return {"FULL":"Vollständig","INCREMENTAL":"Inkrementell","QUICK":"Schnell","AUTO":"Automatisch"}.get(code or "", code or "–")


def _storage_label(code: str | None) -> str:
    return "Backblaze B2 + Neon-Core" if code == "B2" else "Neon – Kleinbackup"


def load_job_report(dsn: str, job_id: str, key_b64: str) -> dict[str, Any]:
    activity("neon", "report")
    with psycopg.connect(dsn, connect_timeout=12) as conn:
        job = conn.execute(
            """
            SELECT id,started_at,finished_at,status,file_count,original_bytes,stored_bytes,deduplicated_bytes,
                   note,trigger_type,plan_name,backup_mode,scanned_count,changed_count,skipped_count,payload_target,
                   directory_count,active_duration_seconds,avg_speed_bps,peak_transfer_bps,compression_saved_bytes,
                   chunk_count,largest_file_bytes,scan_duration_seconds,upload_stage_seconds,processing_seconds,
                   b2_request_seconds,metadata_seconds,upload_worker_count,app_version
            FROM backup_vault.backup_jobs WHERE id=%s
            """, (job_id,)
        ).fetchone()
        if not job:
            raise ValueError("Backup-Job nicht gefunden.")
        cols = [
            "id","started_at","finished_at","status","file_count","original_bytes","stored_bytes","deduplicated_bytes",
            "note","trigger_type","plan_name","backup_mode","scanned_count","changed_count","skipped_count","payload_target",
            "directory_count","active_duration_seconds","avg_speed_bps","peak_transfer_bps","compression_saved_bytes",
            "chunk_count","largest_file_bytes","scan_duration_seconds","upload_stage_seconds","processing_seconds",
            "b2_request_seconds","metadata_seconds","upload_worker_count","app_version"
        ]
        data = dict(zip(cols, job))

        # Storage split based on physical chunks of this job.
        split_rows = conn.execute(
            """
            SELECT c.storage_backend,COALESCE(sum(c.stored_bytes),0),count(*)
            FROM backup_vault.file_chunks c
            JOIN backup_vault.files f ON f.id=c.file_id
            WHERE f.job_id=%s
            GROUP BY c.storage_backend
            """, (job_id,)
        ).fetchall()
        split = {r[0]: {"bytes": int(r[1] or 0), "chunks": int(r[2] or 0)} for r in split_rows}

        # Count distinct encrypted paths locally, never exposing them in Neon.
        dirs = set()
        files = conn.execute(
            """
            SELECT original_path,file_name,original_size,status
            FROM backup_vault.files WHERE job_id=%s ORDER BY original_size DESC
            """, (job_id,)
        ).fetchall()
        largest_name = "–"
        for enc_path, enc_name, original_size, status in files:
            try:
                dirs.add(decrypt_text(key_b64, enc_path))
            except Exception:
                pass
        if files:
            try:
                largest_name = decrypt_text(key_b64, files[0][1])
            except Exception:
                largest_name = "[nicht entschlüsselbar]"
        if not data.get("directory_count"):
            data["directory_count"] = len(dirs)

        latest_verify = conn.execute(
            """
            SELECT mode,result,finished_at,checked_files,checked_chunks,checked_bytes,missing_objects,hash_failures,details
            FROM backup_vault.backup_verifications WHERE job_id=%s
            ORDER BY finished_at DESC NULLS LAST,id DESC LIMIT 1
            """, (job_id,)
        ).fetchone()
        last_full = conn.execute(
            """
            SELECT result,finished_at,checked_files,checked_bytes,details
            FROM backup_vault.backup_verifications
            WHERE job_id=%s AND mode='FULL'
            ORDER BY finished_at DESC NULLS LAST,id DESC LIMIT 1
            """, (job_id,)
        ).fetchone()

    duration = float(data.get("active_duration_seconds") or 0)
    if not duration and data.get("finished_at") and data.get("started_at"):
        duration = max(0.0, (data["finished_at"] - data["started_at"]).total_seconds())
    avg_speed = int(data.get("avg_speed_bps") or 0)
    if not avg_speed and duration > 0:
        avg_speed = int((data.get("original_bytes") or 0) / duration)

    original = int(data.get("original_bytes") or 0)
    stored = int(data.get("stored_bytes") or 0)
    dedup = int(data.get("deduplicated_bytes") or 0)
    efficiency = (stored / original * 100.0) if original else 0.0

    if data["status"] == "SUCCESS":
        if latest_verify and latest_verify[1] == "PASS":
            overall = "GRÜN"
        elif latest_verify and latest_verify[1] == "FAIL":
            overall = "ROT"
        else:
            overall = "GELB"
    elif data["status"] in ("CANCELLED", "PARTIAL"):
        overall = "GELB"
    else:
        overall = "ROT"

    data.update({
        "mode_label": _mode_label(data.get("backup_mode")),
        "storage_label": _storage_label(data.get("payload_target")),
        "duration_seconds": duration,
        "avg_speed_bps": avg_speed,
        "storage_split": split,
        "largest_file_name": largest_name,
        "efficiency_percent": efficiency,
        "latest_verification": latest_verify,
        "last_full_verification": last_full,
        "overall": overall,
        "report_generated_at": datetime.now().astimezone(),
    })
    return data


def report_lines(r: dict[str, Any]) -> list[str]:
    verify = r.get("latest_verification")
    full = r.get("last_full_verification")
    split = r.get("storage_split") or {}
    b2 = split.get("B2", {"bytes":0,"chunks":0})
    neon = split.get("NEON", {"bytes":0,"chunks":0})
    status_title = {
        "GRÜN": "BACKUP / PRÜFSTATUS GRÜN",
        "GELB": "BACKUP MIT HINWEIS",
        "ROT": "BACKUP / PRÜFSTATUS ROT",
    }.get(r.get("overall"), "BACKUP-REPORT")
    lines = [
        "PC BACKUP VAULT – BACKUP-REPORT",
        status_title,
        "=" * 64,
        f"Job-ID: {r['id']}",
        f"App-Version: {r.get('app_version') or '–'}",
        f"Start: {r['started_at']:%d.%m.%Y %H:%M:%S}" if r.get("started_at") else "Start: –",
        f"Ende: {r['finished_at']:%d.%m.%Y %H:%M:%S}" if r.get("finished_at") else "Ende: –",
        f"Status: {r.get('status')}",
        f"Sicherungsart: {r.get('mode_label')}",
        f"Speicher: {r.get('storage_label')}",
        f"Auslöser: {r.get('trigger_type') or '–'}",
        f"Plan: {r.get('plan_name') or '–'}",
        "",
        "UMFANG",
        f"Geprüfte/ausgewählte Dateien: {int(r.get('scanned_count') or 0):,}".replace(",", "."),
        f"Verzeichnisse: {int(r.get('directory_count') or 0):,}".replace(",", "."),
        f"Neu/geändert: {int(r.get('changed_count') or 0):,}".replace(",", "."),
        f"Unverändert/übersprungen: {int(r.get('skipped_count') or 0):,}".replace(",", "."),
        f"Größte Datei: {r.get('largest_file_name')} – {human_size(r.get('largest_file_bytes'))}",
        f"Original-Datenmenge: {human_size(r.get('original_bytes'))}",
        f"Neu gespeichert/übertragen: {human_size(r.get('stored_bytes'))}",
        f"Deduplizierung gespart: {human_size(r.get('deduplicated_bytes'))}",
        f"Kompression gespart: {human_size(r.get('compression_saved_bytes'))}",
        f"Effizienz: {r.get('efficiency_percent',0):.1f}% neu gespeichert bezogen auf geprüfte Daten",
        "",
        "SPEICHER / CHUNKS",
        f"B2: {human_size(b2.get('bytes'))} · {b2.get('chunks',0)} Chunk(s)",
        f"Neon-Payload: {human_size(neon.get('bytes'))} · {neon.get('chunks',0)} Chunk(s)",
        f"Chunks gesamt: {int(r.get('chunk_count') or 0):,}".replace(",", "."),
        "",
        "ZEIT / LEISTUNG",
        f"Aktive Dauer: {fmt_duration(r.get('duration_seconds'))}",
        f"Ø Gesamtgeschwindigkeit: {human_size(r.get('avg_speed_bps'))}/s",
        f"Transfer-Spitze: {human_size(r.get('peak_transfer_bps'))}/s" if r.get('peak_transfer_bps') else "Transfer-Spitze: –",
        f"Prüfung / Hash: {fmt_duration(r.get('scan_duration_seconds'))}",
        f"B2-Upload-Phase: {fmt_duration(r.get('upload_stage_seconds'))}" if r.get('payload_target') == 'B2' else "B2-Upload-Phase: –",
        f"Parallele B2-Worker: {int(r.get('upload_worker_count') or 1)}" if r.get('payload_target') == 'B2' else "Parallele B2-Worker: –",
        f"Verarbeitung (kumuliert): {fmt_duration(r.get('processing_seconds'))}",
        f"B2-Netzwerkzeit (kumuliert): {fmt_duration(r.get('b2_request_seconds'))}" if r.get('payload_target') == 'B2' else "B2-Netzwerkzeit: –",
        f"Neon-Metadatenzeit: {fmt_duration(r.get('metadata_seconds'))}",
        "",
        "VERIFIZIERUNG",
    ]
    if verify:
        lines.extend([
            f"Letzte Prüfung: {verify[0]} / {verify[1]}",
            f"Zeitpunkt: {verify[2]:%d.%m.%Y %H:%M:%S}" if verify[2] else "Zeitpunkt: –",
            f"Geprüft: {verify[3]} Datei(en), {verify[4]} Chunk(s), {human_size(verify[5])}",
            f"Fehlende Objekte: {verify[6]} · Hashfehler: {verify[7]}",
            f"Details: {verify[8] or '–'}",
        ])
    else:
        lines.append("Noch keine Verifizierung für diesen Job gespeichert.")
    if full:
        lines.append(f"Letzte Vollprüfung: {full[0]} – {full[1]:%d.%m.%Y %H:%M:%S}" if full[1] else f"Letzte Vollprüfung: {full[0]}")
    else:
        lines.append("Vollprüfung: noch nicht durchgeführt.")
    if r.get("note"):
        lines.extend(["", "HINWEISE / FEHLER", str(r.get("note"))])
    lines.extend(["", f"Report erzeugt: {r['report_generated_at']:%d.%m.%Y %H:%M:%S}"])
    return lines


def report_text(r: dict[str, Any]) -> str:
    return "\n".join(report_lines(r)) + "\n"


def save_report_txt(r: dict[str, Any], path: str | Path):
    Path(path).write_text(report_text(r), encoding="utf-8")


def save_report_csv(r: dict[str, Any], path: str | Path):
    fields = {
        "job_id": r.get("id"),
        "start": r.get("started_at"),
        "ende": r.get("finished_at"),
        "status": r.get("status"),
        "gesamtstatus": r.get("overall"),
        "sicherungsart": r.get("mode_label"),
        "speicher": r.get("storage_label"),
        "dateien_geprueft": r.get("scanned_count"),
        "verzeichnisse": r.get("directory_count"),
        "neu_geaendert": r.get("changed_count"),
        "uebersprungen": r.get("skipped_count"),
        "original_bytes": r.get("original_bytes"),
        "stored_bytes": r.get("stored_bytes"),
        "dedup_bytes": r.get("deduplicated_bytes"),
        "compression_saved_bytes": r.get("compression_saved_bytes"),
        "duration_seconds": r.get("duration_seconds"),
        "avg_speed_bps": r.get("avg_speed_bps"),
        "peak_transfer_bps": r.get("peak_transfer_bps"),
        "scan_duration_seconds": r.get("scan_duration_seconds"),
        "upload_stage_seconds": r.get("upload_stage_seconds"),
        "processing_seconds": r.get("processing_seconds"),
        "b2_request_seconds": r.get("b2_request_seconds"),
        "metadata_seconds": r.get("metadata_seconds"),
        "upload_worker_count": r.get("upload_worker_count"),
        "chunks": r.get("chunk_count"),
    }
    with Path(path).open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh, delimiter=";")
        writer.writerow(["Feld", "Wert"])
        for k, v in fields.items():
            writer.writerow([k, "" if v is None else str(v)])
