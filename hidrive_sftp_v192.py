from __future__ import annotations

import posixpath
import uuid
from contextlib import contextmanager
from pathlib import PurePosixPath

import paramiko

from cloud_targets_v191 import cloud_account, effective_endpoint, get_cloud_secret


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
    transport = paramiko.Transport((host, port))
    try:
        transport.connect(username=user, password=password)
        sftp = paramiko.SFTPClient.from_transport(transport)
        try:
            yield sftp, account
        finally:
            sftp.close()
    finally:
        transport.close()


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


def test_hidrive_sftp(store, account_id):
    try:
        with sftp_connection(store, account_id) as (sftp, account):
            root = _root(account)
            sftp.chdir(root)
            probe = posixpath.join(root, f".pbv-test-{uuid.uuid4().hex}.tmp")
            with sftp.file(probe, "wb") as fh:
                fh.write(b"PC Backup Vault HiDrive SFTP test")
            with sftp.file(probe, "rb") as fh:
                if fh.read() != b"PC Backup Vault HiDrive SFTP test":
                    raise RuntimeError("SFTP-Testdatei wurde verändert gelesen.")
            sftp.remove(probe)
            return True, f"SFTP-Anmeldung sowie Lesen/Schreiben/Löschen erfolgreich: {root}"
    except Exception as exc:
        return False, f"HiDrive-SFTP-Test fehlgeschlagen: {exc}"


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
