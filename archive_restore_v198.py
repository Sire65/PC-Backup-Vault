from __future__ import annotations

import hashlib
import json
import posixpath
from pathlib import Path, PureWindowsPath

from crypto_box import decrypt_bytes, decrypt_text, sha256_bytes
from hidrive_sftp_v192 import VAULT_DIR as HIDRIVE_VAULT_DIR, _root, sftp_connection
from job_archive_v198 import get_job, index_manifest, record_restore_event
from storage_v180 import VAULT_DIR as FS_VAULT_DIR


def _safe_rel(original_path: str, file_name: str) -> Path:
    """Return a relative, traversal-safe restore path for archived Windows metadata."""
    p = PureWindowsPath(original_path or "")
    parts = []
    if p.drive:
        drive = p.drive.replace(": " , "").replace(":", "").replace("\\", "").replace("/", "").strip()
        if drive:
            parts.append(drive)
    for value in p.parts:
        clean = str(value).strip("\\/")
        if not clean or value == p.drive or clean in (".", ".."):
            continue
        parts.append(clean)
    safe_name = PureWindowsPath(str(file_name or "wiederhergestellt")).name
    safe_name = safe_name.replace("/", "").replace("\\", "").strip() or "wiederhergestellt"
    return Path(*parts) / safe_name


def _keep_both(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    index = 1
    while True:
        candidate = path.with_name(f"{stem} (wiederhergestellt {index}){suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def _load_local_manifest(target: dict, job_id: str) -> tuple[dict, Path]:
    root = Path(str(target.get("path") or "")) / FS_VAULT_DIR
    path = root / "jobs" / f"{job_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"Job-Manifest nicht gefunden: {path}")
    return json.loads(path.read_text(encoding="utf-8")), root


def _restore_manifest_local(app, manifest: dict, vault_root: Path, destination: Path) -> dict:
    key = app.master_key()
    if not key:
        raise RuntimeError("Wiederherstellungsschlüssel ist nicht verfügbar.")
    restored = 0
    restored_bytes = 0
    for item in manifest.get("files") or []:
        original_path = decrypt_text(key, str(item.get("path") or ""))
        name = decrypt_text(key, str(item.get("name") or ""))
        out = _keep_both(destination / _safe_rel(original_path, name))
        out.parent.mkdir(parents=True, exist_ok=True)
        temp = out.with_name(out.name + ".pcbv-restore.tmp")
        digest = hashlib.sha256()
        try:
            with temp.open("wb") as dst:
                for ref in sorted(item.get("chunks") or [], key=lambda x: int(x.get("no") or 0)):
                    payload = (vault_root / "chunks" / str(ref["file"])).read_bytes()
                    nonce, cipher = payload[:12], payload[12:]
                    if sha256_bytes(cipher) != str(ref.get("cipher_sha256") or ""):
                        raise RuntimeError(f"Integritätsfehler im verschlüsselten Chunk von {name}.")
                    aad = f"{item['sha256']}:{int(ref.get('no') or 0)}".encode("ascii")
                    raw = decrypt_bytes(key, nonce, cipher, aad)
                    dst.write(raw)
                    digest.update(raw)
                    restored_bytes += len(raw)
            if digest.hexdigest() != str(item.get("sha256") or ""):
                raise RuntimeError(f"SHA-256-Prüfung nach Wiederherstellung fehlgeschlagen: {name}")
            temp.replace(out)
        except Exception:
            temp.unlink(missing_ok=True)
            raise
        restored += 1
    return {"files": restored, "bytes": restored_bytes, "destination": str(destination)}


def _match_hidrive_account(store, job: dict):
    locator = job.get("locator") or {}
    account_id = str(locator.get("account_id") or "")
    accounts = list(store.data.get("cloud_accounts") or [])
    if account_id:
        account = next((a for a in accounts if str(a.get("id")) == account_id), None)
        if account:
            return account
    target_label = str(job.get("target_label") or "").lower()
    for account in accounts:
        name = str(account.get("name") or "").strip()
        if name and name.lower() in target_label:
            return account
    return None


def _match_filesystem_target(store, job: dict):
    locator = job.get("locator") or {}
    target_id = str(locator.get("target_id") or "")
    targets = list(store.data.get("filesystem_targets") or [])
    if target_id:
        target = next((t for t in targets if str(t.get("id")) == target_id), None)
        if target:
            return target
    label = str(job.get("target_label") or "").lower()
    return next((t for t in targets if str(t.get("name") or "").lower() in label), None)


def _read_sftp_bytes(sftp, path: str) -> bytes:
    with sftp.file(path, "rb") as fh:
        return fh.read()


def _restore_manifest_sftp(app, sftp, account: dict, manifest: dict, destination: Path) -> dict:
    key = app.master_key()
    if not key:
        raise RuntimeError("Wiederherstellungsschlüssel ist nicht verfügbar.")
    chunks_root = posixpath.join(_root(account), HIDRIVE_VAULT_DIR, "chunks")
    restored = 0
    restored_bytes = 0
    for item in manifest.get("files") or []:
        original_path = decrypt_text(key, str(item.get("path") or ""))
        name = decrypt_text(key, str(item.get("name") or ""))
        out = _keep_both(destination / _safe_rel(original_path, name))
        out.parent.mkdir(parents=True, exist_ok=True)
        temp = out.with_name(out.name + ".pcbv-restore.tmp")
        digest = hashlib.sha256()
        try:
            with temp.open("wb") as dst:
                for ref in sorted(item.get("chunks") or [], key=lambda x: int(x.get("no") or 0)):
                    payload = _read_sftp_bytes(sftp, posixpath.join(chunks_root, str(ref["file"])))
                    nonce, cipher = payload[:12], payload[12:]
                    if sha256_bytes(cipher) != str(ref.get("cipher_sha256") or ""):
                        raise RuntimeError(f"Integritätsfehler im HiDrive-Chunk von {name}.")
                    aad = f"{item['sha256']}:{int(ref.get('no') or 0)}".encode("ascii")
                    raw = decrypt_bytes(key, nonce, cipher, aad)
                    dst.write(raw)
                    digest.update(raw)
                    restored_bytes += len(raw)
            if digest.hexdigest() != str(item.get("sha256") or ""):
                raise RuntimeError(f"SHA-256-Prüfung nach HiDrive-Wiederherstellung fehlgeschlagen: {name}")
            temp.replace(out)
        except Exception:
            temp.unlink(missing_ok=True)
            raise
        restored += 1
    return {"files": restored, "bytes": restored_bytes, "destination": str(destination)}


def restore_archived_job(app, job_id: str, destination: str | Path) -> dict:
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
                manifest_path = posixpath.join(_root(live_account), HIDRIVE_VAULT_DIR, "jobs", f"{job_id}.json")
                manifest = json.loads(_read_sftp_bytes(sftp, manifest_path).decode("utf-8"))
                index_manifest(app.store, job_id, manifest, "STRATO HiDrive", job_id)
                result = _restore_manifest_sftp(app, sftp, live_account, manifest, destination)
        elif kind == "FILESYSTEM" or str(job.get("payload_target") or "").upper() == "FILESYSTEM":
            target = _match_filesystem_target(app.store, job)
            if not target:
                raise RuntimeError("Das zu diesem Archiv-Job gehörende Laufwerk/NAS-Ziel ist nicht mehr konfiguriert.")
            manifest, vault_root = _load_local_manifest(target, job_id)
            index_manifest(app.store, job_id, manifest, job.get("backend_label") or "FILESYSTEM", job_id)
            result = _restore_manifest_local(app, manifest, vault_root, destination)
        else:
            raise RuntimeError("DATABASE_RESTORE")
    except Exception as exc:
        if str(exc) != "DATABASE_RESTORE":
            record_restore_event(app.store, job_id, "FAILED", str(destination), details=str(exc))
        raise
    record_restore_event(app.store, job_id, "PASS", str(destination), result["files"], result["bytes"], "PASS", "SHA-256 nach Wiederherstellung geprüft")
    return result
