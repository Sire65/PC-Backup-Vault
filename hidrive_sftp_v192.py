from __future__ import annotations

import hashlib
import json
import os
import posixpath
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path, PurePosixPath

import paramiko

from backup_engine import BackupControl, collect_paths
from cloud_targets_v191 import cloud_account, effective_endpoint, get_cloud_secret
from config_store import APP_VERSION
from crypto_box import encrypt_bytes, encrypt_text, sha256_bytes

VAULT_DIR = ".pc-backup-vault"
CHUNK_SIZE = 8 * 1024 * 1024


def _host_port(account):
    endpoint = effective_endpoint(account, "SFTP") or "sftp.hidrive.strato.com"
    endpoint = endpoint.replace("sftp://", "").strip().rstrip("/")
    host_port = endpoint.split("/", 1)[0]
    if ":" in host_port:
        host, port = host_port.rsplit(":", 1)
        return host, int(port)
    return host_port, 22


def _root(account):
    configured = str(account.get("root_path") or "").strip()
    if configured:
        return "/" + configured.strip("/")
    user = str(account.get("username") or "").strip()
    return f"/users/{user}"


def _known_hosts_files():
    candidates = [Path.home() / ".ssh" / "known_hosts"]
    userprofile = os.environ.get("USERPROFILE")
    if userprofile:
        candidates.append(Path(userprofile) / ".ssh" / "known_hosts")
    seen = set()
    for path in candidates:
        key = str(path).lower()
        if key not in seen and path.exists():
            seen.add(key)
            yield path


def _strict_client(host, port, username, password):
    client = paramiko.SSHClient()
    loaded = False
    for path in _known_hosts_files():
        try:
            client.load_host_keys(str(path))
            loaded = True
        except Exception:
            pass
    if not loaded:
        raise RuntimeError(
            "Der SFTP-Server ist noch nicht im Windows-SSH-Vertrauensspeicher hinterlegt. "
            "Bitte den STRATO-Zugang einmal mit dem Windows-SFTP-Test verbinden und den Host-Schlüssel bestätigen."
        )
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    try:
        client.connect(
            hostname=host,
            port=port,
            username=username,
            password=password,
            timeout=12,
            banner_timeout=12,
            auth_timeout=12,
            allow_agent=False,
            look_for_keys=False,
        )
    except paramiko.BadHostKeyException as exc:
        raise RuntimeError("Sicherheitsstopp: Der HiDrive-Host-Schlüssel stimmt nicht mit dem bekannten Schlüssel überein.") from exc
    except paramiko.AuthenticationException as exc:
        raise RuntimeError("HiDrive-Anmeldung abgelehnt. Benutzername/Passwort oder SFTP-Freigabe prüfen.") from exc
    return client


@contextmanager
def sftp_connection(store, account_id):
    account = cloud_account(store, account_id)
    if not account:
        raise RuntimeError("HiDrive-Konto nicht gefunden.")
    user = str(account.get("username") or "").strip()
    password = get_cloud_secret(account_id, "password")
    if not user or not password:
        raise RuntimeError("HiDrive-Benutzername oder Passwort fehlt.")
    host, port = _host_port(account)
    client = _strict_client(host, port, user, password)
    try:
        sftp = client.open_sftp()
        try:
            yield sftp, account
        finally:
            sftp.close()
    finally:
        client.close()


def _mkdirs(sftp, path):
    current = "/"
    for part in PurePosixPath(path).parts:
        if part in ("/", ""):
            continue
        current = posixpath.join(current, part)
        try:
            sftp.stat(current)
        except OSError:
            sftp.mkdir(current)


def _exists(sftp, path):
    try:
        sftp.stat(path)
        return True
    except OSError:
        return False


def _write_bytes(sftp, remote, payload):
    _mkdirs(sftp, posixpath.dirname(remote))
    with sftp.file(remote, "wb") as fh:
        fh.write(payload)
        fh.flush()


def test_hidrive_sftp(store, account_id):
    try:
        with sftp_connection(store, account_id) as (sftp, account):
            root = _root(account)
            _mkdirs(sftp, root)
            sftp.chdir(root)
            probe = posixpath.join(root, f".pbv-test-{uuid.uuid4().hex}.tmp")
            payload = b"PC Backup Vault HiDrive SFTP test"
            _write_bytes(sftp, probe, payload)
            with sftp.file(probe, "rb") as fh:
                if fh.read() != payload:
                    raise RuntimeError("SFTP-Testdatei wurde verändert gelesen.")
            sftp.remove(probe)
            return True, f"SFTP-Anmeldung sowie Lesen/Schreiben/Löschen erfolgreich: {root}"
    except Exception as exc:
        return False, f"HiDrive-SFTP-Test fehlgeschlagen: {exc}"


def filesystem_backup_sftp(app, paths, target, control=None, progress=None, plan_name=None):
    """Encrypt locally in memory and write the normal PCBV-FS vault layout via SFTP."""
    account_id = str(target.get("cloud_account_id") or "")
    if not account_id:
        raise RuntimeError("HiDrive-Konto am Backup-Ziel fehlt.")
    control = control or BackupControl()
    paths = collect_paths(paths, control=control)
    if not paths:
        raise RuntimeError("Keine erreichbaren Dateien für das HiDrive-Backup gefunden.")

    total = sum(p.stat().st_size for p in paths)
    done = 0
    files_done = 0
    stored = 0
    peak = 0.0
    started = time.monotonic()
    manifest = []

    with sftp_connection(app.store, account_id) as (sftp, account):
        base = posixpath.join(_root(account), VAULT_DIR)
        chunks_root = posixpath.join(base, "chunks")
        jobs_root = posixpath.join(base, "jobs")
        _mkdirs(sftp, chunks_root)
        _mkdirs(sftp, jobs_root)

        probe = posixpath.join(base, f".write-test-{os.getpid()}-{uuid.uuid4().hex[:8]}")
        _write_bytes(sftp, probe, b"PCBV")
        sftp.remove(probe)

        for p in paths:
            control.check()
            stat = p.stat()
            sha = hashlib.sha256()
            with p.open("rb") as fh:
                while True:
                    control.check()
                    block = fh.read(1024 * 1024)
                    if not block:
                        break
                    sha.update(block)
            file_sha = sha.hexdigest()
            refs = []
            chunk_no = 0
            with p.open("rb") as fh:
                while True:
                    control.check()
                    raw = fh.read(CHUNK_SIZE)
                    if not raw:
                        break
                    aad = f"{file_sha}:{chunk_no}".encode("ascii")
                    nonce, cipher = encrypt_bytes(app.master_key(), raw, aad)
                    chash = sha256_bytes(cipher)
                    rel = f"{file_sha[:2]}/{file_sha}/{chunk_no:06d}-{chash[:12]}.bin"
                    remote = posixpath.join(chunks_root, rel)
                    payload = nonce + cipher
                    t0 = time.monotonic()
                    if not _exists(sftp, remote):
                        _write_bytes(sftp, remote, payload)
                        stored += len(payload)
                    dt = max(0.001, time.monotonic() - t0)
                    speed = len(payload) / dt
                    peak = max(peak, speed)
                    refs.append({"no": chunk_no, "file": rel, "cipher_sha256": chash, "bytes": len(payload)})
                    done += len(raw)
                    chunk_no += 1
                    elapsed = max(0.001, time.monotonic() - started)
                    avg = done / elapsed
                    eta = (total - done) / avg if avg else 0
                    metrics = {
                        "phase": "HiDrive-SFTP-Backup",
                        "bytes_done": done,
                        "bytes_total": total,
                        "transfer_bytes": stored,
                        "current_file": p.name,
                        "elapsed": elapsed,
                        "speed_bps": speed,
                        "peak_bps": peak,
                        "eta_seconds": eta,
                    }
                    if progress:
                        try:
                            progress(files_done, len(paths), f"Sichere {p.name} zu STRATO HiDrive", metrics)
                        except TypeError:
                            progress(files_done, len(paths), f"Sichere {p.name} zu STRATO HiDrive")
            manifest.append({
                "path": encrypt_text(app.master_key(), str(p.parent)),
                "name": encrypt_text(app.master_key(), p.name),
                "sha256": file_sha,
                "original_size": stat.st_size,
                "modified_at": stat.st_mtime,
                "chunks": refs,
            })
            files_done += 1

        elapsed = max(0.001, time.monotonic() - started)
        job_id = str(uuid.uuid4())
        doc = {
            "format": "PCBV-FS-1",
            "transport": "SFTP",
            "provider": "STRATO_HIDRIVE",
            "job_id": job_id,
            "app_version": APP_VERSION,
            "created_at": datetime.now().astimezone().isoformat(),
            "plan_name": plan_name,
            "target_name": target.get("name"),
            "cloud_account_id": account_id,
            "files": manifest,
            "file_count": len(manifest),
            "original_bytes": total,
            "stored_bytes": stored,
            "duration_seconds": elapsed,
            "avg_speed_bps": int(total / elapsed),
            "peak_speed_bps": int(peak),
        }
        encoded = json.dumps(doc, ensure_ascii=False, indent=2).encode("utf-8")
        tmp = posixpath.join(jobs_root, f"{job_id}.json.tmp")
        final = posixpath.join(jobs_root, f"{job_id}.json")
        _write_bytes(sftp, tmp, encoded)
        try:
            sftp.posix_rename(tmp, final)
        except Exception:
            sftp.rename(tmp, final)

    if progress:
        metrics = {
            "phase": "Fertig",
            "bytes_done": total,
            "bytes_total": total,
            "transfer_bytes": stored,
            "current_file": "",
            "elapsed": elapsed,
            "speed_bps": 0,
            "peak_bps": peak,
            "eta_seconds": 0,
        }
        try:
            progress(len(paths), len(paths), "HiDrive-Backup abgeschlossen", metrics)
        except TypeError:
            progress(len(paths), len(paths), "HiDrive-Backup abgeschlossen")

    return {
        "job_id": job_id,
        "status": "SUCCESS",
        "mode": "FILESYSTEM",
        "payload_target": "FILESYSTEM",
        "transport": "SFTP",
        "provider": "STRATO_HIDRIVE",
        "files": len(manifest),
        "original_bytes": total,
        "stored_bytes": stored,
        "duration_seconds": elapsed,
        "avg_speed_bps": int(total / elapsed),
        "peak_transfer_bps": int(peak),
        "target": f"sftp://{_host_port(account)[0]}{_root(account)}/{VAULT_DIR}",
    }


def upload_file(store, account_id, local_path, remote_relative, progress=None):
    with sftp_connection(store, account_id) as (sftp, account):
        root = _root(account)
        remote = posixpath.join(root, remote_relative.replace("\\", "/").lstrip("/"))
        _mkdirs(sftp, posixpath.dirname(remote))
        sftp.put(str(local_path), remote, callback=progress)
        return remote


def download_file(store, account_id, remote_relative, local_path, progress=None):
    with sftp_connection(store, account_id) as (sftp, account):
        root = _root(account)
        remote = posixpath.join(root, remote_relative.replace("\\", "/").lstrip("/"))
        sftp.get(remote, str(local_path), callback=progress)
        return str(local_path)
