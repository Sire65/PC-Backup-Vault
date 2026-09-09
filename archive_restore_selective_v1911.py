from __future__ import annotations

import json
import posixpath
from pathlib import Path

from archive_restore_v198 import (
    HIDRIVE_VAULT_DIR,
    _load_local_manifest,
    _match_filesystem_target,
    _match_hidrive_account,
    _read_sftp_bytes,
    _restore_manifest_local,
    _restore_manifest_sftp,
)
from hidrive_sftp_v192 import _root, sftp_connection
from job_archive_v198 import get_job, index_manifest, record_restore_event


def filter_manifest(manifest: dict, manifest_indices) -> dict:
    """Return a shallow manifest copy containing only explicitly selected file indices."""
    if manifest_indices is None:
        return manifest
    wanted = {int(x) for x in manifest_indices}
    if not wanted:
        raise ValueError("Keine Dateien für die Wiederherstellung ausgewählt.")
    files = list(manifest.get("files") or [])
    selected = [item for index, item in enumerate(files) if index in wanted]
    if not selected:
        raise ValueError("Die ausgewählten Dateien wurden im Job-Manifest nicht gefunden.")
    out = dict(manifest)
    out["files"] = selected
    out["file_count"] = len(selected)
    out["original_bytes"] = sum(max(0, int(item.get("original_size") or 0)) for item in selected)
    return out


def restore_archived_selection(app, job_id: str, destination: str | Path, manifest_indices, progress=None) -> dict:
    """Restore only selected manifest files from HiDrive or filesystem/NAS archive jobs."""
    job = get_job(app.store, job_id)
    if not job:
        raise KeyError(f"Job {job_id} ist nicht im lokalen Archiv vorhanden.")

    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    backend = str(job.get("backend_label") or "").lower()
    locator = job.get("locator") or {}
    kind = str(locator.get("kind") or "").upper()

    try:
        if kind == "HIDRIVE" or "hidrive" in backend or "hidrive" in str(job.get("target_label") or "").lower():
            account = _match_hidrive_account(app.store, job)
            if not account:
                raise RuntimeError("Das zu diesem Archiv-Job gehörende HiDrive-Konto ist nicht mehr konfiguriert.")
            with sftp_connection(app.store, str(account.get("id"))) as (sftp, live_account):
                manifest_path = posixpath.join(
                    _root(live_account), HIDRIVE_VAULT_DIR, "jobs", f"{job_id}.json"
                )
                manifest = json.loads(_read_sftp_bytes(sftp, manifest_path).decode("utf-8"))
                index_manifest(app.store, job_id, manifest, "STRATO HiDrive", job_id)
                selected_manifest = filter_manifest(manifest, manifest_indices)
                result = _restore_manifest_sftp(
                    app, sftp, live_account, selected_manifest, destination, progress
                )
        elif kind == "FILESYSTEM" or str(job.get("payload_target") or "").upper() == "FILESYSTEM":
            target = _match_filesystem_target(app.store, job)
            if not target:
                raise RuntimeError("Das zu diesem Archiv-Job gehörende Laufwerk/NAS-Ziel ist nicht mehr konfiguriert.")
            manifest, vault_root = _load_local_manifest(target, job_id)
            index_manifest(app.store, job_id, manifest, job.get("backend_label") or "FILESYSTEM", job_id)
            selected_manifest = filter_manifest(manifest, manifest_indices)
            result = _restore_manifest_local(app, selected_manifest, vault_root, destination, progress)
        else:
            raise RuntimeError("DATABASE_RESTORE")
    except Exception as exc:
        if str(exc) != "DATABASE_RESTORE":
            record_restore_event(
                app.store, job_id, "FAILED", str(destination), details=str(exc)
            )
        raise

    record_restore_event(
        app.store,
        job_id,
        "PASS",
        str(destination),
        result["files"],
        result["bytes"],
        "PASS",
        "Selektive Wiederherstellung · SHA-256 nach Wiederherstellung geprüft",
    )
    return result
