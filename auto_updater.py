from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

REPOSITORY = "Sire65/PC-Backup-Vault"
LATEST_RELEASE_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
USER_AGENT = "PC-Backup-Vault-Updater"
VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    tag: str
    setup_name: str
    setup_url: str
    setup_size: int
    sha256_name: str
    sha256_url: str
    release_url: str
    notes: str = ""


def _version_tuple(value: str) -> tuple[int, int, int]:
    match = VERSION_RE.match(str(value or "").strip())
    if not match:
        raise ValueError(f"Ungültige Versionsnummer: {value!r}")
    return tuple(int(x) for x in match.groups())


def is_newer_version(current: str, candidate: str) -> bool:
    return _version_tuple(candidate) > _version_tuple(current)


def _get_json(url: str, timeout: int = 12) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_latest_release(current_version: str) -> ReleaseInfo | None:
    """Return the latest verified-release candidate, or None when no update exists.

    Drafts/prereleases and releases without matching setup + SHA-256 assets are ignored.
    """
    try:
        release = _get_json(LATEST_RELEASE_URL)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
        return None

    if release.get("draft") or release.get("prerelease"):
        return None
    tag = str(release.get("tag_name") or "").strip()
    try:
        candidate_version = tag[1:] if tag.lower().startswith("v") else tag
        if not is_newer_version(current_version, candidate_version):
            return None
    except ValueError:
        return None

    expected_setup = f"PC_Backup_Vault_{candidate_version}_Setup.exe"
    expected_sha = expected_setup + ".sha256"
    assets = {str(a.get("name") or ""): a for a in release.get("assets", [])}
    setup = assets.get(expected_setup)
    checksum = assets.get(expected_sha)
    if not setup or not checksum:
        return None
    setup_url = str(setup.get("browser_download_url") or "")
    sha_url = str(checksum.get("browser_download_url") or "")
    if not setup_url.startswith("https://github.com/") or not sha_url.startswith("https://github.com/"):
        return None

    return ReleaseInfo(
        version=candidate_version,
        tag=tag,
        setup_name=expected_setup,
        setup_url=setup_url,
        setup_size=int(setup.get("size") or 0),
        sha256_name=expected_sha,
        sha256_url=sha_url,
        release_url=str(release.get("html_url") or ""),
        notes=str(release.get("body") or ""),
    )


def _download_bytes(url: str, timeout: int = 20) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def fetch_expected_sha256(info: ReleaseInfo) -> str:
    raw = _download_bytes(info.sha256_url).decode("utf-8", errors="strict").strip()
    digest = raw.split()[0].lower() if raw else ""
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise RuntimeError("Die Release-Prüfsumme ist ungültig.")
    return digest


def default_update_dir() -> Path:
    base = os.environ.get("APPDATA")
    root = Path(base) / "PCBackupVault" if base else Path.home() / ".pcbackupvault"
    path = root / "updates"
    path.mkdir(parents=True, exist_ok=True)
    return path


def download_and_verify(
    info: ReleaseInfo,
    *,
    target_dir: str | Path | None = None,
    progress: Callable[[int, int, str], None] | None = None,
) -> Path:
    """Download setup to a partial file, SHA-256 verify it, then atomically publish locally."""
    expected = fetch_expected_sha256(info)
    root = Path(target_dir) if target_dir else default_update_dir()
    root.mkdir(parents=True, exist_ok=True)
    final_path = root / info.setup_name
    partial_path = root / (info.setup_name + ".part")
    partial_path.unlink(missing_ok=True)

    request = urllib.request.Request(info.setup_url, headers={"User-Agent": USER_AGENT})
    digest = hashlib.sha256()
    received = 0
    try:
        with urllib.request.urlopen(request, timeout=30) as response, partial_path.open("wb") as fh:
            total = int(response.headers.get("Content-Length") or info.setup_size or 0)
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                fh.write(chunk)
                digest.update(chunk)
                received += len(chunk)
                if progress:
                    progress(received, total, "Update wird heruntergeladen…")
    except Exception:
        partial_path.unlink(missing_ok=True)
        raise

    if digest.hexdigest().lower() != expected:
        partial_path.unlink(missing_ok=True)
        raise RuntimeError("SHA-256-Prüfung fehlgeschlagen. Das Update wird aus Sicherheitsgründen nicht installiert.")

    os.replace(partial_path, final_path)
    if progress:
        progress(received, received, "SHA-256 geprüft · Update bereit")
    return final_path


def launch_installer(setup_path: str | Path) -> None:
    """Start the verified Inno Setup detached. The caller should then close the running app."""
    path = Path(setup_path).resolve()
    if not path.is_file() or path.suffix.lower() != ".exe":
        raise RuntimeError("Das geprüfte Setup wurde nicht gefunden.")
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(
        [str(path), "/SP-", "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS"],
        cwd=str(path.parent),
        close_fds=True,
        creationflags=creationflags,
    )
