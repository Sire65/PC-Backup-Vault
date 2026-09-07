from __future__ import annotations

import base64
import os
import socket
import uuid
from pathlib import Path
from typing import Any
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

import keyring

from config_store import SERVICE


PROVIDERS: dict[str, dict[str, Any]] = {
    "STRATO_HIDRIVE": {
        "name": "STRATO HiDrive",
        "methods": ["SMB", "WEBDAV", "SFTP"],
        "defaults": {
            "WEBDAV": "https://webdav.hidrive.strato.com",
            "SFTP": "sftp.hidrive.strato.com",
        },
        "ports": {"SMB": 445, "WEBDAV": 443, "SFTP": 22},
    },
    "MICROSOFT_ONEDRIVE": {
        "name": "Microsoft OneDrive",
        "methods": ["OAUTH", "LOCAL_SYNC"],
        "defaults": {},
        "ports": {},
    },
    "DROPBOX": {
        "name": "Dropbox",
        "methods": ["OAUTH", "LOCAL_SYNC"],
        "defaults": {},
        "ports": {},
    },
    "GENERIC_WEBDAV": {
        "name": "WebDAV – anderer Anbieter",
        "methods": ["WEBDAV"],
        "defaults": {},
        "ports": {"WEBDAV": 443},
    },
    "GENERIC_SFTP": {
        "name": "SFTP – anderer Anbieter",
        "methods": ["SFTP"],
        "defaults": {},
        "ports": {"SFTP": 22},
    },
    "GENERIC_SMB": {
        "name": "SMB / Netzlaufwerk – anderer Anbieter",
        "methods": ["SMB"],
        "defaults": {},
        "ports": {"SMB": 445},
    },
    "GENERIC_SYNC": {
        "name": "Lokaler Cloud-Sync-Ordner",
        "methods": ["LOCAL_SYNC"],
        "defaults": {},
        "ports": {},
    },
}

METHOD_LABELS = {
    "SMB": "SMB / Windows-Netzlaufwerk",
    "WEBDAV": "WebDAV (HTTPS)",
    "SFTP": "SFTP (SSH)",
    "OAUTH": "OAuth / Anbieter-API",
    "LOCAL_SYNC": "Lokaler Sync-Ordner",
}


def ensure_cloud_config(store) -> None:
    changed = False
    if "cloud_accounts" not in store.data:
        store.data["cloud_accounts"] = []
        changed = True
    if "cloud_provider_settings" not in store.data:
        store.data["cloud_provider_settings"] = {}
        changed = True
    if changed:
        store.save()


def cloud_accounts(store) -> list[dict[str, Any]]:
    ensure_cloud_config(store)
    return list(store.data.get("cloud_accounts") or [])


def cloud_account(store, account_id: str | None) -> dict[str, Any] | None:
    if not account_id:
        return None
    return next((x for x in cloud_accounts(store) if x.get("id") == account_id), None)


def _secret_key(account_id: str, key: str) -> str:
    return f"cloud:{account_id}:{key}"


def set_cloud_secret(account_id: str, key: str, value: str) -> None:
    value = str(value or "")
    if value:
        keyring.set_password(SERVICE, _secret_key(account_id, key), value)
    else:
        try:
            keyring.delete_password(SERVICE, _secret_key(account_id, key))
        except Exception:
            pass


def get_cloud_secret(account_id: str, key: str) -> str:
    try:
        return keyring.get_password(SERVICE, _secret_key(account_id, key)) or ""
    except Exception:
        return ""


def save_cloud_account(store, data: dict[str, Any], password: str | None = None) -> str:
    ensure_cloud_config(store)
    item = dict(data or {})
    account_id = str(item.get("id") or uuid.uuid4())
    provider_code = str(item.get("provider_code") or "STRATO_HIDRIVE").upper()
    if provider_code not in PROVIDERS:
        raise ValueError("Unbekannter Cloud-Anbieter.")
    supported = set(PROVIDERS[provider_code]["methods"])
    methods = [str(x).upper() for x in (item.get("methods") or []) if str(x).upper() in supported]
    if not methods:
        methods = list(PROVIDERS[provider_code]["methods"][:1])
    preferred = str(item.get("preferred_method") or methods[0]).upper()
    if preferred not in methods:
        preferred = methods[0]
    clean = {
        "id": account_id,
        "name": str(item.get("name") or PROVIDERS[provider_code]["name"]).strip(),
        "provider_code": provider_code,
        "enabled": bool(item.get("enabled", True)),
        "methods": methods,
        "preferred_method": preferred,
        "username": str(item.get("username") or "").strip(),
        "endpoint": str(item.get("endpoint") or "").strip(),
        "root_path": str(item.get("root_path") or "").strip(),
        "local_path": str(item.get("local_path") or "").strip(),
        "notes": str(item.get("notes") or "").strip(),
    }
    rows = store.data.get("cloud_accounts") or []
    old = next((x for x in rows if x.get("id") == account_id), None)
    if old is None:
        rows.append(clean)
    else:
        old.clear(); old.update(clean)
    store.data["cloud_accounts"] = rows
    store.save()
    if password is not None:
        set_cloud_secret(account_id, "password", password)
    return account_id


def delete_cloud_account(store, account_id: str) -> None:
    ensure_cloud_config(store)
    store.data["cloud_accounts"] = [x for x in cloud_accounts(store) if x.get("id") != account_id]
    # Remove only the generated filesystem bridge, never payload data.
    store.data["filesystem_targets"] = [
        x for x in (store.data.get("filesystem_targets") or []) if x.get("cloud_account_id") != account_id
    ]
    store.save()
    for key in ("password", "oauth_token", "refresh_token"):
        set_cloud_secret(account_id, key, "")


def provider_name(code: str) -> str:
    return str((PROVIDERS.get(code) or {}).get("name") or code)


def strato_smb_path(username: str) -> str:
    user = str(username or "").strip().lower()
    if not user:
        return r"\\smb3.hidrive.strato.com\root"
    # Unique host alias allows multiple HiDrive credentials on one Windows machine.
    return rf"\\{user}.smb3.hidrive.strato.com\root"


def effective_endpoint(account: dict[str, Any], method: str | None = None) -> str:
    method = str(method or account.get("preferred_method") or "").upper()
    explicit = str(account.get("endpoint") or "").strip()
    if explicit:
        return explicit
    provider = str(account.get("provider_code") or "")
    if provider == "STRATO_HIDRIVE" and method == "SMB":
        return strato_smb_path(account.get("username") or "")
    return str((PROVIDERS.get(provider) or {}).get("defaults", {}).get(method) or "")


def _write_probe(path: str) -> tuple[bool, str]:
    root = Path(path)
    if not root.exists() or not root.is_dir():
        return False, f"Pfad nicht erreichbar: {path}"
    probe = root / f".pbv-cloud-test-{os.getpid()}-{uuid.uuid4().hex[:8]}.tmp"
    try:
        probe.write_bytes(b"PC Backup Vault cloud target test")
        data = probe.read_bytes()
        if data != b"PC Backup Vault cloud target test":
            raise RuntimeError("Testdatei konnte nicht unverändert gelesen werden.")
        probe.unlink(missing_ok=True)
        return True, f"Lesen/Schreiben/Löschen erfolgreich: {path}"
    except Exception as exc:
        try:
            probe.unlink(missing_ok=True)
        except Exception:
            pass
        return False, f"Cloud-Ziel nicht vollständig beschreibbar: {exc}"


def _connect_windows_smb(remote: str, username: str, password: str) -> None:
    if os.name != "nt":
        return
    if not remote.startswith("\\\\"):
        raise ValueError("SMB-Ziel muss ein UNC-Pfad sein.")
    import ctypes
    from ctypes import wintypes

    class NETRESOURCEW(ctypes.Structure):
        _fields_ = [
            ("dwScope", wintypes.DWORD), ("dwType", wintypes.DWORD), ("dwDisplayType", wintypes.DWORD),
            ("dwUsage", wintypes.DWORD), ("lpLocalName", wintypes.LPWSTR), ("lpRemoteName", wintypes.LPWSTR),
            ("lpComment", wintypes.LPWSTR), ("lpProvider", wintypes.LPWSTR),
        ]

    nr = NETRESOURCEW(0, 1, 0, 0, None, remote, None, None)
    result = ctypes.windll.mpr.WNetAddConnection2W(ctypes.byref(nr), password or None, username or None, 0)
    # 0=OK, 85=already assigned, 1219=Windows already has a connection to same server under another credential.
    if result not in (0, 85):
        if result == 1219:
            raise RuntimeError(
                "Windows verwendet für diesen Server bereits andere Zugangsdaten. Für mehrere HiDrive-Konten den benutzerspezifischen SMB-Host verwenden."
            )
        raise OSError(result, f"Windows-SMB-Verbindung fehlgeschlagen (Fehler {result}).")


def prepare_cloud_filesystem_target(store, target: dict[str, Any]) -> dict[str, Any]:
    account_id = str(target.get("cloud_account_id") or "")
    if not account_id:
        return target
    account = cloud_account(store, account_id)
    if not account or not account.get("enabled", True):
        raise RuntimeError("Das zugehörige Cloud-Konto ist deaktiviert oder wurde gelöscht.")
    method = str(target.get("cloud_method") or account.get("preferred_method") or "").upper()
    path = str(target.get("path") or "").strip()
    if method == "SMB":
        remote = path or effective_endpoint(account, "SMB")
        _connect_windows_smb(remote, str(account.get("username") or ""), get_cloud_secret(account_id, "password"))
        target["path"] = remote
        return target
    if method == "LOCAL_SYNC":
        if not path:
            raise RuntimeError("Für dieses Cloud-Konto ist noch kein lokaler Sync-Ordner hinterlegt.")
        return target
    raise RuntimeError(
        f"{METHOD_LABELS.get(method, method)} ist als Konto-Zugang vorbereitet, aber noch kein direkter Backup-Transport. "
        "Bitte SMB oder einen lokalen Sync-Ordner als aktive Backup-Methode wählen."
    )


def filesystem_capable_method(account: dict[str, Any]) -> str | None:
    methods = [str(x).upper() for x in (account.get("methods") or [])]
    preferred = str(account.get("preferred_method") or "").upper()
    order = [preferred] + [x for x in methods if x != preferred]
    for method in order:
        if method == "SMB":
            return method
        if method == "LOCAL_SYNC" and str(account.get("local_path") or "").strip():
            return method
    return None


def ensure_filesystem_bridge(store, account_id: str) -> dict[str, Any]:
    account = cloud_account(store, account_id)
    if not account:
        raise ValueError("Cloud-Konto nicht gefunden.")
    method = filesystem_capable_method(account)
    if not method:
        raise RuntimeError(
            "Dieses Cloud-Konto hat noch keine vom Backup-Core direkt nutzbare Methode. "
            "Bitte SMB oder einen lokalen Sync-Ordner aktivieren."
        )
    if method == "SMB":
        path = str(account.get("endpoint") or "").strip() or effective_endpoint(account, "SMB")
    else:
        path = str(account.get("local_path") or "").strip()
    if str(account.get("root_path") or "").strip() and method == "LOCAL_SYNC":
        path = str(Path(path) / str(account.get("root_path") or "").strip("\\/"))
    target_id = f"cloud-{account_id}"
    item = {
        "id": target_id,
        "name": f"Cloud · {account.get('name') or provider_name(account.get('provider_code',''))}",
        "path": path,
        "kind": "CLOUD-SMB" if method == "SMB" else "CLOUD-SYNC",
        "volume_hint": "CLOUD",
        "cloud_account_id": account_id,
        "cloud_method": method,
    }
    rows = store.data.setdefault("filesystem_targets", [])
    old = next((x for x in rows if x.get("id") == target_id), None)
    if old is None:
        rows.append(item)
    else:
        old.clear(); old.update(item)
    store.data["active_filesystem_target_id"] = target_id
    store.save()
    return item


def _webdav_test(account: dict[str, Any], password: str) -> tuple[bool, str]:
    endpoint = effective_endpoint(account, "WEBDAV").rstrip("/") + "/"
    if not endpoint.lower().startswith("https://"):
        return False, "WebDAV-Endpunkt muss HTTPS verwenden."
    user = str(account.get("username") or "")
    token = base64.b64encode(f"{user}:{password}".encode("utf-8")).decode("ascii")
    req = urlrequest.Request(endpoint, method="PROPFIND", headers={"Depth": "0", "Authorization": f"Basic {token}"})
    try:
        with urlrequest.urlopen(req, timeout=12) as resp:
            code = int(getattr(resp, "status", 0) or 0)
            if code in (200, 207):
                return True, f"WebDAV-Anmeldung erfolgreich ({code})."
            return False, f"WebDAV antwortet mit HTTP {code}."
    except HTTPError as exc:
        if exc.code in (200, 207):
            return True, f"WebDAV-Anmeldung erfolgreich ({exc.code})."
        return False, f"WebDAV-Anmeldung fehlgeschlagen: HTTP {exc.code}."
    except URLError as exc:
        return False, f"WebDAV nicht erreichbar: {exc.reason}"
    except Exception as exc:
        return False, f"WebDAV-Test fehlgeschlagen: {exc}"


def _tcp_test(host: str, port: int) -> tuple[bool, str]:
    try:
        with socket.create_connection((host, int(port)), timeout=8):
            return True, f"Server {host}:{port} erreichbar."
    except Exception as exc:
        return False, f"Server {host}:{port} nicht erreichbar: {exc}"


def test_cloud_account(store, account_id: str, method: str | None = None) -> tuple[bool, str]:
    account = cloud_account(store, account_id)
    if not account:
        return False, "Cloud-Konto nicht gefunden."
    method = str(method or account.get("preferred_method") or "").upper()
    if method not in (account.get("methods") or []):
        return False, "Diese Verbindungsmethode ist für das Konto nicht aktiviert."
    if method == "LOCAL_SYNC":
        return _write_probe(str(account.get("local_path") or ""))
    if method == "SMB":
        path = str(account.get("endpoint") or "").strip() or effective_endpoint(account, "SMB")
        try:
            _connect_windows_smb(path, str(account.get("username") or ""), get_cloud_secret(account_id, "password"))
        except Exception as exc:
            return False, str(exc)
        return _write_probe(path)
    if method == "WEBDAV":
        return _webdav_test(account, get_cloud_secret(account_id, "password"))
    if method == "SFTP":
        endpoint = effective_endpoint(account, "SFTP")
        host = endpoint.replace("sftp://", "").split("/")[0].split(":")[0]
        port = int((PROVIDERS.get(account.get("provider_code")) or {}).get("ports", {}).get("SFTP", 22))
        ok, msg = _tcp_test(host, port)
        if ok:
            msg += " Zugangsdatenprüfung folgt erst mit dem direkten SFTP-Transport."
        return ok, msg
    if method == "OAUTH":
        token = get_cloud_secret(account_id, "oauth_token")
        return (bool(token), "OAuth-Verbindung vorhanden." if token else "OAuth-Verbindung noch nicht autorisiert.")
    return False, "Unbekannte Verbindungsmethode."
