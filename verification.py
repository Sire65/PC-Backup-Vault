from __future__ import annotations

import hashlib
import time
import zlib
from dataclasses import dataclass
from datetime import datetime

import psycopg
from status_bus import activity

from backup_engine import BackupCancelled
from crypto_box import decrypt_bytes, sha256_bytes
from object_store import make_b2_store


@dataclass
class VerifyResult:
    verification_id: int | None
    job_id: str
    mode: str
    result: str
    checked_files: int
    checked_chunks: int
    checked_bytes: int
    missing_objects: int
    hash_failures: int
    duration_seconds: float
    details: str

    def as_dict(self):
        return self.__dict__.copy()


def _emit(progress, done, total, message, *, bytes_done=0, bytes_total=0, started=None):
    if not progress:
        return
    metrics = {
        "phase": "Verifizierung",
        "files_done": int(done),
        "files_total": int(total),
        "bytes_done": int(bytes_done),
        "bytes_total": int(bytes_total),
        "current_file": message,
        "elapsed": max(0.0, time.monotonic() - started) if started else 0.0,
    }
    try:
        progress(done, total, message, metrics)
    except TypeError:
        progress(done, total, message)


def latest_successful_job_id(dsn: str) -> str | None:
    activity("neon", "verify")
    with psycopg.connect(dsn, connect_timeout=8) as conn:
        row = conn.execute(
            "SELECT id FROM backup_vault.backup_jobs WHERE status='SUCCESS' ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        return str(row[0]) if row else None


def _record_verification(conn, job_id, mode, result, started_at, checked_files, checked_chunks,
                         checked_bytes, missing_objects, hash_failures, details, app_version):
    row = conn.execute(
        """
        INSERT INTO backup_vault.backup_verifications
        (job_id, mode, started_at, finished_at, result, checked_files, checked_chunks,
         checked_bytes, missing_objects, hash_failures, details, app_version)
        VALUES (%s,%s,%s,now(),%s,%s,%s,%s,%s,%s,%s,%s)
        RETURNING id
        """,
        (job_id, mode, started_at, result, checked_files, checked_chunks, checked_bytes,
         missing_objects, hash_failures, details[:4000], app_version),
    ).fetchone()
    return int(row[0]) if row else None


def verify_job(dsn: str, key_b64: str, job_id: str, mode: str = "QUICK", object_store_config=None,
               progress=None, control=None, app_version="unknown") -> VerifyResult:
    """Verify one successful backup job.

    QUICK validates database consistency and object existence/size without downloading payloads.
    FULL downloads every unique payload referenced by the job, validates encrypted chunk SHA-256,
    decrypts/decompresses locally, and validates the final file SHA-256 and original size.
    Files skipped as unchanged by incremental/quick backup are not uploaded in that job; the result
    explicitly reports that those files continue to rely on their previous verified version.
    """
    mode = (mode or "QUICK").upper()
    if mode not in {"QUICK", "FULL"}:
        raise ValueError("Ungültiger Verifizierungsmodus.")

    started_at = datetime.now().astimezone()
    started_mono = time.monotonic()
    checked_files = checked_chunks = checked_bytes = missing_objects = hash_failures = 0
    details_parts: list[str] = []

    try:
        activity("neon", "verify")
        with psycopg.connect(dsn, connect_timeout=12) as conn:
            job = conn.execute(
                """
                SELECT id,status,scanned_count,changed_count,skipped_count,payload_target,started_at,finished_at
                FROM backup_vault.backup_jobs WHERE id=%s
                """, (job_id,)
            ).fetchone()
            if not job:
                raise ValueError("Backup-Job wurde nicht gefunden.")
            if job[1] != "SUCCESS":
                raise ValueError(f"Nur erfolgreiche Backups können verifiziert werden (Status: {job[1]}).")

            files = conn.execute(
                """
                SELECT id,sha256,compression,status,original_size,chunk_count,payload_backend
                FROM backup_vault.files
                WHERE job_id=%s AND status IN ('STORED','DEDUPED')
                ORDER BY created_at,id
                """, (job_id,)
            ).fetchall()
            scanned_count = int(job[2] or 0)
            skipped_count = int(job[4] or 0)
            total_bytes = sum(int(f[4] or 0) for f in files)
            b2_store = make_b2_store(object_store_config)

            # Resolve every deduplicated row to its physical source once.
            resolved = []
            for f in files:
                if control is not None:
                    control.check()
                fid, sha, comp, status, original_size, chunk_count, backend = f
                source_id, source_comp, source_backend = fid, comp, backend
                if status == "DEDUPED":
                    src = conn.execute(
                        """
                        SELECT id,compression,payload_backend
                        FROM backup_vault.files
                        WHERE sha256=%s AND status='STORED' AND payload_backend=%s
                        ORDER BY created_at ASC LIMIT 1
                        """, (sha, backend)
                    ).fetchone()
                    if not src:
                        hash_failures += 1
                        details_parts.append(f"Deduplikationsquelle fehlt für SHA {sha[:12]}…")
                        resolved.append((f, None, None, None))
                        continue
                    source_id, source_comp, source_backend = src
                resolved.append((f, source_id, source_comp, source_backend))

            if mode == "QUICK":
                expected_b2: dict[str, int] = {}
                quick_seen_sources: set[str] = set()
                for idx, (f, source_id, source_comp, source_backend) in enumerate(resolved, start=1):
                    if control is not None:
                        control.check()
                    fid, sha, comp, status, original_size, chunk_count, backend = f
                    if source_id is None:
                        continue
                    source_key=str(source_id)
                    if source_key not in quick_seen_sources:
                        quick_seen_sources.add(source_key)
                        chunks = conn.execute(
                            """
                            SELECT chunk_no,encrypted_data,chunk_sha256,stored_bytes,storage_backend,object_key
                            FROM backup_vault.file_chunks WHERE file_id=%s ORDER BY chunk_no
                            """, (source_id,)
                        ).fetchall()
                        if status == "STORED" and int(chunk_count or 0) != len(chunks):
                            hash_failures += 1
                            details_parts.append(f"Chunk-Anzahl stimmt nicht für SHA {sha[:12]}…")
                        for chunk in chunks:
                            checked_chunks += 1
                            chunk_no, encrypted_data, chunk_sha, stored_bytes, storage_backend, object_key = chunk
                            if storage_backend == "NEON":
                                if encrypted_data is None or len(bytes(encrypted_data)) != int(stored_bytes or 0):
                                    hash_failures += 1
                                elif sha256_bytes(bytes(encrypted_data)) != chunk_sha:
                                    hash_failures += 1
                            elif storage_backend == "B2":
                                if not object_key:
                                    missing_objects += 1
                                else:
                                    expected_b2[str(object_key)] = int(stored_bytes or 0)
                            else:
                                hash_failures += 1
                    checked_files += 1
                    checked_bytes += int(original_size or 0)
                    _emit(progress, idx, len(resolved), f"Metadaten: {idx}/{len(resolved)}", bytes_done=checked_bytes,
                          bytes_total=total_bytes, started=started_mono)

                if expected_b2:
                    if b2_store is None:
                        missing_objects += len(expected_b2)
                        details_parts.append("B2-Zugang ist für die Objektprüfung nicht eingerichtet.")
                    else:
                        objects = b2_store.list_prefix_sizes()
                        for key, expected_size in expected_b2.items():
                            actual_size = objects.get(key)
                            if actual_size is None:
                                missing_objects += 1
                            elif int(actual_size) != int(expected_size):
                                hash_failures += 1
                if skipped_count:
                    details_parts.append(
                        f"{skipped_count} unveränderte Datei(en) wurden im Sicherungslauf absichtlich nicht neu übertragen; "
                        "sie bleiben durch ihre vorherige Version abgedeckt."
                    )
            else:
                # Verify physical payload only once per (sha, backend), even if job contains deduplicated references.
                verified_payloads: set[tuple[str, str]] = set()
                for idx, (f, source_id, source_comp, source_backend) in enumerate(resolved, start=1):
                    if control is not None:
                        control.check()
                    fid, sha, comp, status, original_size, chunk_count, backend = f
                    if source_id is None:
                        continue
                    payload_key = (str(sha), str(source_backend))
                    if payload_key not in verified_payloads:
                        chunks = conn.execute(
                            """
                            SELECT chunk_no,nonce,encrypted_data,chunk_sha256,stored_bytes,storage_backend,object_key
                            FROM backup_vault.file_chunks WHERE file_id=%s ORDER BY chunk_no
                            """, (source_id,)
                        ).fetchall()
                        h = hashlib.sha256()
                        physical_size = 0
                        for chunk_no, nonce, encrypted_data, chunk_sha, stored_bytes, storage_backend, object_key in chunks:
                            if control is not None:
                                control.check()
                            if storage_backend == "B2":
                                if b2_store is None or not object_key:
                                    missing_objects += 1
                                    raise RuntimeError("B2-Objekt kann nicht gelesen werden.")
                                cipher = b2_store.get(str(object_key))
                            else:
                                if encrypted_data is None:
                                    raise RuntimeError("Neon-Chunk enthält keine Daten.")
                                cipher = bytes(encrypted_data)
                            checked_chunks += 1
                            if len(cipher) != int(stored_bytes or 0) or sha256_bytes(cipher) != chunk_sha:
                                hash_failures += 1
                                raise RuntimeError("Chunk-Integritätsprüfung fehlgeschlagen.")
                            payload = decrypt_bytes(key_b64, bytes(nonce), cipher, f"{sha}:{chunk_no}".encode("ascii"))
                            raw = zlib.decompress(payload) if source_comp == "ZLIB" else payload
                            h.update(raw)
                            physical_size += len(raw)
                        if h.hexdigest() != sha or physical_size != int(original_size or 0):
                            hash_failures += 1
                            raise RuntimeError("Datei-SHA-256 oder Originalgröße stimmt nicht.")
                        verified_payloads.add(payload_key)
                    checked_files += 1
                    checked_bytes += int(original_size or 0)
                    _emit(progress, idx, len(resolved), f"Inhalt: {idx}/{len(resolved)}", bytes_done=checked_bytes,
                          bytes_total=total_bytes, started=started_mono)
                if skipped_count:
                    details_parts.append(
                        f"{skipped_count} unveränderte Datei(en) gehörten zum Lauf, wurden aber nicht neu gespeichert; "
                        "die Vollprüfung dieses Jobs prüft alle neu gespeicherten/referenzierten Inhalte."
                    )

            result = "PASS" if missing_objects == 0 and hash_failures == 0 else "FAIL"
            if not files and scanned_count > 0 and skipped_count == scanned_count:
                result = "PASS"
                details_parts.append("Der Lauf enthielt ausschließlich unveränderte, übersprungene Dateien.")
            details = " ".join(details_parts) or "Alle geprüften Backup-Daten sind konsistent."
            verification_id = _record_verification(
                conn, job_id, mode, result, started_at, checked_files, checked_chunks,
                checked_bytes, missing_objects, hash_failures, details, app_version,
            )
            activity("neon", "commit")
            conn.commit()
            return VerifyResult(
                verification_id=verification_id,
                job_id=str(job_id), mode=mode, result=result,
                checked_files=checked_files, checked_chunks=checked_chunks,
                checked_bytes=checked_bytes, missing_objects=missing_objects,
                hash_failures=hash_failures,
                duration_seconds=max(0.0, time.monotonic() - started_mono), details=details,
            )
    except BackupCancelled:
        try:
            activity("neon", "verify")
            with psycopg.connect(dsn) as conn:
                verification_id = _record_verification(
                    conn, job_id, mode, "CANCELLED", started_at, checked_files, checked_chunks,
                    checked_bytes, missing_objects, hash_failures, "Vom Benutzer abgebrochen.", app_version,
                )
                activity("neon", "commit")
                conn.commit()
        except Exception:
            verification_id = None
        raise
    except Exception as exc:
        details_parts.append(str(exc))
        details = " ".join(details_parts)
        try:
            activity("neon", "verify")
            with psycopg.connect(dsn) as conn:
                verification_id = _record_verification(
                    conn, job_id, mode, "FAIL", started_at, checked_files, checked_chunks,
                    checked_bytes, missing_objects, max(1, hash_failures), details, app_version,
                )
                activity("neon", "commit")
                conn.commit()
        except Exception:
            verification_id = None
        return VerifyResult(
            verification_id=verification_id, job_id=str(job_id), mode=mode, result="FAIL",
            checked_files=checked_files, checked_chunks=checked_chunks, checked_bytes=checked_bytes,
            missing_objects=missing_objects, hash_failures=max(1, hash_failures),
            duration_seconds=max(0.0, time.monotonic() - started_mono), details=details,
        )
