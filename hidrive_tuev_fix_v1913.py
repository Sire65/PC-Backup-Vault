from __future__ import annotations

import hashlib
import json
import posixpath
from contextlib import contextmanager

from crypto_box import decrypt_bytes, sha256_bytes
from hidrive_sftp_v192 import VAULT_DIR, _root, sftp_connection, test_hidrive_sftp


MAX_REMOTE_CHUNK_PROBES = 12


def _is_hidrive_target(target: dict | None) -> bool:
    target = target or {}
    return (
        str(target.get("kind") or "").upper() == "CLOUD-SFTP"
        and str(target.get("cloud_method") or "").upper() == "SFTP"
        and bool(target.get("cloud_account_id"))
    )


def _account(store, account_id: str) -> dict | None:
    return next(
        (
            dict(a)
            for a in list(store.data.get("cloud_accounts") or [])
            if str(a.get("id") or "") == str(account_id or "")
        ),
        None,
    )


def _read_bytes(sftp, path: str) -> bytes:
    with sftp.file(path, "rb") as fh:
        return fh.read()


def _latest_remote_manifest(sftp, account: dict) -> tuple[dict | None, str | None]:
    jobs_root = posixpath.join(_root(account), VAULT_DIR, "jobs")
    try:
        attrs = [a for a in sftp.listdir_attr(jobs_root) if str(getattr(a, "filename", "")).endswith(".json")]
    except OSError:
        return None, None
    if not attrs:
        return None, None
    attrs.sort(key=lambda a: int(getattr(a, "st_mtime", 0) or 0), reverse=True)
    path = posixpath.join(jobs_root, str(attrs[0].filename))
    doc = json.loads(_read_bytes(sftp, path).decode("utf-8"))
    return doc, path


def _sample_chunk_refs(manifest: dict, limit: int = MAX_REMOTE_CHUNK_PROBES) -> list[dict]:
    refs = [
        dict(ref)
        for item in list(manifest.get("files") or [])
        for ref in list(item.get("chunks") or [])
        if ref.get("file")
    ]
    if len(refs) <= limit:
        return refs
    positions = {0, len(refs) - 1}
    if limit > 2:
        step = (len(refs) - 1) / float(limit - 1)
        positions.update(round(i * step) for i in range(limit))
    return [refs[i] for i in sorted(positions)[:limit]]


def _verify_remote_manifest_presence(sftp, account: dict, manifest: dict) -> tuple[str, str]:
    if str(manifest.get("format") or "") != "PCBV-FS-1":
        return "FAIL", "HiDrive-Manifest hat ein unbekanntes Format"
    files = list(manifest.get("files") or [])
    if not files:
        return "WARN", "Letzter HiDrive-Backup-Stand enthält keine Dateien"
    refs = _sample_chunk_refs(manifest)
    chunks_root = posixpath.join(_root(account), VAULT_DIR, "chunks")
    for ref in refs:
        remote = posixpath.join(chunks_root, str(ref.get("file") or ""))
        try:
            stat = sftp.stat(remote)
        except OSError:
            return "FAIL", f"Referenzierter HiDrive-Chunk fehlt: {posixpath.basename(remote)}"
        if int(getattr(stat, "st_size", 13) or 0) < 13:
            return "FAIL", f"HiDrive-Chunk ist unvollständig: {posixpath.basename(remote)}"
    return "PASS", f"{len(files)} Dateien im Manifest · {len(refs)} Chunk-Verweise remote geprüft"


def _remote_restore_probe(sftp, account: dict, manifest: dict, key_b64: str, max_kb: int) -> tuple[str, str]:
    limit = max(1, int(max_kb or 256)) * 1024
    candidates = [
        item for item in list(manifest.get("files") or [])
        if list(item.get("chunks") or []) and 0 < int(item.get("original_size") or 0) <= limit
    ]
    if not candidates:
        return "WARN", f"Keine Datei bis {max(1, int(max_kb or 256))} KB für automatische HiDrive-Restore-Probe"
    item = min(candidates, key=lambda x: int(x.get("original_size") or 0))
    chunks_root = posixpath.join(_root(account), VAULT_DIR, "chunks")
    digest = hashlib.sha256()
    try:
        for ref in sorted(item.get("chunks") or [], key=lambda x: int(x.get("no") or 0)):
            remote = posixpath.join(chunks_root, str(ref.get("file") or ""))
            payload = _read_bytes(sftp, remote)
            if len(payload) < 13:
                return "FAIL", f"HiDrive-Restore-Probe: Chunk unvollständig ({posixpath.basename(remote)})"
            nonce, cipher = payload[:12], payload[12:]
            if sha256_bytes(cipher) != str(ref.get("cipher_sha256") or ""):
                return "FAIL", "HiDrive-Restore-Probe: verschlüsselte Chunk-Prüfsumme stimmt nicht"
            aad = f"{item.get('sha256')}:{int(ref.get('no') or 0)}".encode("ascii")
            digest.update(decrypt_bytes(key_b64, nonce, cipher, aad))
    except Exception as exc:
        return "FAIL", f"HiDrive-Restore-Probe fehlgeschlagen: {exc}"
    if digest.hexdigest() != str(item.get("sha256") or ""):
        return "FAIL", "HiDrive-Restore-Probe: Datei-SHA-256 stimmt nach Entschlüsselung nicht"
    return "PASS", "HiDrive-Restore-Probe erfolgreich · Entschlüsselung und SHA-256 PASS"


def _hidrive_checks(store, key_b64: str, target: dict, index: int) -> list[tuple[str, str, str, str]]:
    name = target.get("name") or f"HiDrive {index}"
    account_id = str(target.get("cloud_account_id") or "")
    account = _account(store, account_id)
    if not account:
        return [
            (f"FS-{index:03d}", f"Ziel {name}", "WARN", "HiDrive-Konto zum Backup-Ziel nicht gefunden"),
            (f"FSV-{index:03d}", f"Letzter Stand {name}", "WARN", "HiDrive-Katalog nicht prüfbar"),
        ]

    ok, message = test_hidrive_sftp(store, account_id)
    if not ok:
        return [
            (f"FS-{index:03d}", f"Ziel {name}", "WARN", message),
            (f"FSV-{index:03d}", f"Letzter Stand {name}", "WARN", "HiDrive-Katalog wegen Verbindungsfehler nicht geprüft"),
        ]

    checks = [(f"FS-{index:03d}", f"Ziel {name}", "PASS", "SFTP verbunden · Lesen/Schreiben/Löschen erfolgreich")]
    try:
        with sftp_connection(store, account_id) as (sftp, live_account):
            manifest, _manifest_path = _latest_remote_manifest(sftp, live_account)
            if not manifest:
                checks.append((f"FSV-{index:03d}", f"Letzter Stand {name}", "WARN", "Noch kein HiDrive-Backup-Stand vorhanden"))
                return checks
            result, detail = _verify_remote_manifest_presence(sftp, live_account, manifest)
            checks.append((f"FSV-{index:03d}", f"Letzter Stand {name}", result, detail))
            if result == "FAIL":
                return checks
            restore_result, restore_detail = _remote_restore_probe(
                sftp,
                live_account,
                manifest,
                key_b64,
                int(store.data.get("restore_selftest_max_kb", 256) or 256),
            )
            checks.append((f"FSR-{index:03d}", f"Restore-Probe {name}", restore_result, restore_detail))
            return checks
    except Exception as exc:
        checks.append((f"FSV-{index:03d}", f"Letzter Stand {name}", "WARN", f"HiDrive-Katalog konnte nicht gelesen werden: {exc}"))
        return checks


def apply_hidrive_tuev_fix_v1913(professional_module):
    """Replace only the filesystem TÜV dispatcher; local USB/NAS behavior stays unchanged."""
    if getattr(professional_module, "_hidrive_tuev_fix_v1913", False):
        return

    def filesystem_tuev_checks(store, key_b64: str):
        checks = []
        targets = list(professional_module._targets(store))
        if not targets:
            return [("FS-001", "Dateisystem-Ziele", "WARN", "Noch kein USB-/NAS-Ziel eingerichtet")]

        for i, target in enumerate(targets, 1):
            if _is_hidrive_target(target):
                checks.extend(_hidrive_checks(store, key_b64, target, i))
                continue

            name = target.get("name") or f"Ziel {i}"
            path = target.get("path") or ""
            pre = professional_module.preflight_filesystem_target(target, [], 0)
            checks.append((
                f"FS-{i:03d}",
                f"Ziel {name}",
                "PASS" if pre.get("ok") else "WARN",
                path if pre.get("ok") else "; ".join(x["detail"] for x in pre["checks"] if not x["ok"])[:500],
            ))
            jobs = professional_module.list_filesystem_jobs(target)
            if jobs:
                vr = professional_module.verify_filesystem_job(target, jobs[0], key_b64, full=False)
                checks.append((
                    f"FSV-{i:03d}",
                    f"Letzter Stand {name}",
                    vr["result"],
                    f"{vr['checked_files']} Dateien / {vr['checked_chunks']} Chunks" + ("" if not vr["errors"] else " · " + vr["errors"][0][:250]),
                ))
                st = professional_module.filesystem_restore_selftest(
                    target,
                    key_b64,
                    int(store.data.get("restore_selftest_max_kb", 256)),
                )
                checks.append((f"FSR-{i:03d}", f"Restore-Probe {name}", st["status"], st["details"]))
            else:
                checks.append((f"FSV-{i:03d}", f"Letzter Stand {name}", "WARN", "Noch kein Backup-Stand vorhanden"))
        return checks

    professional_module.filesystem_tuev_checks = filesystem_tuev_checks
    professional_module._hidrive_tuev_fix_v1913 = True


def _walk(widget):
    for child in widget.winfo_children():
        yield child
        yield from _walk(child)


def apply_explorer_labels_v1913(AppClass, JobArchiveWindow):
    """Make the already existing restore explorer discoverable without changing restore behavior."""
    if not getattr(AppClass, "_explorer_labels_v1913", False):
        original_build = AppClass._build

        def _build(self):
            original_build(self)
            for widget in _walk(self):
                try:
                    if str(widget.cget("text")) == "🗄 Job-Archiv":
                        widget.configure(text="🔎 Backup-Explorer")
                except Exception:
                    pass

        AppClass._build = _build
        AppClass._explorer_labels_v1913 = True

    if not getattr(JobArchiveWindow, "_explorer_labels_v1913", False):
        original_init = JobArchiveWindow.__init__

        def __init__(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            for widget in _walk(self):
                try:
                    if str(widget.cget("text")) == "📄 Dateien anzeigen":
                        widget.configure(text="🔎 Explorer öffnen")
                except Exception:
                    pass
            try:
                self.restore_btn.configure(text="♻ Im Explorer auswählen")
            except Exception:
                pass

        JobArchiveWindow.__init__ = __init__
        JobArchiveWindow._explorer_labels_v1913 = True
