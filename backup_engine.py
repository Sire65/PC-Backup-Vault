from __future__ import annotations
import hashlib, mimetypes, zlib, time, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from datetime import datetime
import psycopg
from status_bus import activity
from crypto_box import encrypt_bytes, decrypt_bytes, encrypt_text, decrypt_text, sha256_bytes, logical_path_hmac
from object_store import make_b2_store

CHUNK_SIZE = 2 * 1024 * 1024
B2_CHUNK_SIZE = 8 * 1024 * 1024
ALREADY_COMPRESSED = {
    ".zip", ".7z", ".rar", ".gz", ".bz2", ".xz", ".jpg", ".jpeg", ".png", ".gif", ".webp",
    ".pdf", ".docx", ".xlsx", ".pptx", ".mp4", ".mkv", ".mov", ".avi", ".mp3", ".aac",
    ".flac", ".ogg", ".heic", ".heif"
}

class LimitBlocked(RuntimeError):
    pass

class ChristmasGuard(RuntimeError):
    pass


class BackupCancelled(RuntimeError):
    """Cooperative user cancellation at a safe checkpoint."""
    pass


class BackupControl:
    """Low-overhead cooperative pause/resume/cancel controller.

    Pause never kills an in-flight database or B2 request. The worker reaches a
    safe checkpoint, finishes the current small block/request, and then waits.
    """
    def __init__(self):
        self._run_event = threading.Event()
        self._run_event.set()
        self._cancel_event = threading.Event()
        self._lock = threading.Lock()
        self._paused_at = None
        self._paused_total = 0.0

    def pause(self):
        with self._lock:
            if self._cancel_event.is_set() or not self._run_event.is_set():
                return
            self._paused_at = time.monotonic()
            self._run_event.clear()

    def resume(self):
        with self._lock:
            if self._run_event.is_set():
                return
            if self._paused_at is not None:
                self._paused_total += max(0.0, time.monotonic() - self._paused_at)
                self._paused_at = None
            self._run_event.set()

    def cancel(self):
        self._cancel_event.set()
        self.resume()  # unblock a paused worker so it can exit at once

    @property
    def paused(self):
        return not self._run_event.is_set() and not self._cancel_event.is_set()

    @property
    def cancelled(self):
        return self._cancel_event.is_set()

    def check(self):
        if self._cancel_event.is_set():
            raise BackupCancelled("Backup wurde vom Benutzer abgebrochen.")
        while not self._run_event.wait(0.20):
            if self._cancel_event.is_set():
                raise BackupCancelled("Backup wurde vom Benutzer abgebrochen.")
        if self._cancel_event.is_set():
            raise BackupCancelled("Backup wurde vom Benutzer abgebrochen.")

    def elapsed(self, started_mono: float) -> float:
        now = time.monotonic()
        with self._lock:
            paused_total = self._paused_total
            if self._paused_at is not None:
                paused_total += max(0.0, now - self._paused_at)
        return max(0.0, now - started_mono - paused_total)


def _control_check(control):
    if control is not None:
        control.check()


def _active_elapsed(control, started_mono):
    return control.elapsed(started_mono) if control is not None else max(0.0, time.monotonic()-started_mono)


def guard_active(config: dict) -> bool:
    if not config.get("christmas_guard", True):
        return False
    today = datetime.now().date()
    return today.month == 12 and 4 <= today.day <= 13


def _emit_progress(progress, files_done, files_total, message, **metrics):
    """Backward-compatible progress callback with optional live metrics."""
    if not progress:
        return
    metrics.setdefault("files_done", int(files_done))
    metrics.setdefault("files_total", int(files_total))
    metrics.setdefault("message", message)
    try:
        progress(files_done, files_total, message, metrics)
    except TypeError:
        progress(files_done, files_total, message)


def file_sha256(path: Path, on_bytes=None, control=None) -> str:
    h = hashlib.sha256()
    done = 0
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            _control_check(control)
            h.update(block)
            done += len(block)
            if on_bytes:
                on_bytes(done)
    return h.hexdigest()


def choose_compression(path: Path) -> str:
    if path.suffix.lower() in ALREADY_COMPRESSED:
        return "NONE"
    try:
        with path.open("rb") as f:
            sample = f.read(1024 * 1024)
        if len(sample) < 1024:
            return "NONE"
        packed = zlib.compress(sample, 6)
        return "ZLIB" if len(packed) <= int(len(sample) * 0.92) else "NONE"
    except Exception:
        return "NONE"


def estimate_payload(path: Path, compression: str) -> int:
    size = path.stat().st_size
    if compression == "NONE":
        return int(size * 1.06) + 4096
    try:
        with path.open("rb") as f:
            sample = f.read(min(1024 * 1024, size))
        ratio = len(zlib.compress(sample, 6)) / max(1, len(sample))
        ratio = max(0.05, min(1.0, ratio))
        return int(size * ratio * 1.08) + 4096
    except Exception:
        return int(size * 1.08) + 4096


def collect_paths(items, control=None):
    out, seen = [], set()
    for raw in items:
        _control_check(control)
        p = Path(raw)
        if p.is_file():
            candidates = [p]
        elif p.is_dir():
            candidates = (x for x in p.rglob("*") if x.is_file())
        else:
            candidates = []
        for x in candidates:
            _control_check(control)
            try:
                key = str(x.resolve()).lower()
            except Exception:
                key = str(x).lower()
            if key not in seen:
                seen.add(key)
                out.append(x)
    return out


def record_usage_snapshot(conn, hard_limit_bytes: int):
    db_size = int(conn.execute("SELECT pg_database_size(current_database())").fetchone()[0])
    payload = int(conn.execute("SELECT COALESCE(sum(stored_size),0) FROM backup_vault.files WHERE status IN ('STORED','DEDUPED')").fetchone()[0] or 0)
    percent = round((db_size / hard_limit_bytes) * 100, 2) if hard_limit_bytes else 0
    status = 'BLOCK' if percent >= 100 else ('WARN' if percent >= 85 else 'OK')
    conn.execute(
        """
        INSERT INTO backup_vault.usage_snapshots(captured_at, database_bytes, file_payload_bytes, percent_of_hard_limit, status)
        VALUES (now(), %s, %s, %s, %s)
        """,
        (db_size, payload, percent, status)
    )


def mark_cleanup_eligibility(conn, logical_hmacs, keep_last_versions: int):
    logical_hmacs = list({x for x in logical_hmacs if x})
    if not logical_hmacs:
        return
    conn.execute(
        """
        WITH ranked AS (
          SELECT id, row_number() OVER (PARTITION BY logical_path_hmac ORDER BY created_at DESC) AS rn
          FROM backup_vault.files
          WHERE logical_path_hmac = ANY(%s)
        )
        UPDATE backup_vault.files f
        SET cleanup_eligible = (r.rn > %s AND COALESCE(f.retention_until, f.created_at) <= now())
        FROM ranked r
        WHERE f.id = r.id
        """,
        (logical_hmacs, int(keep_last_versions)),
    )


def recommend_backup_mode(dsn: str, paths) -> tuple[str, str]:
    """Return (mode, human-readable reason) for the next backup."""
    count = len(paths or [])
    total = sum(p.stat().st_size for p in (paths or []) if p.exists())
    try:
        activity("neon", "backup")
        with psycopg.connect(dsn, connect_timeout=8) as conn:
            latest = conn.execute(
                "SELECT status,started_at,backup_mode FROM backup_vault.backup_jobs ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
            last_success = conn.execute(
                "SELECT started_at,backup_mode FROM backup_vault.backup_jobs WHERE status='SUCCESS' ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
            last_full = conn.execute(
                "SELECT started_at FROM backup_vault.backup_jobs WHERE status='SUCCESS' AND backup_mode='FULL' ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
    except Exception:
        return "INCREMENTAL", "Historie nicht vollständig auswertbar – sichere Standardempfehlung: Inkrementell."

    if not last_success:
        return "FULL", "Noch keine erfolgreiche Sicherung vorhanden – zuerst vollständigen Ausgangsstand erstellen."
    if latest and latest[0] in ("FAILED", "PARTIAL", "BLOCKED_LIMIT", "INTERRUPTED"):
        return "FULL", "Der letzte Lauf war nicht vollständig erfolgreich – Vollprüfung empfohlen."
    if not last_full:
        return "FULL", "Es gibt noch keinen bestätigten Voll-Stand – vollständige Sicherung empfohlen."

    now = datetime.now(last_full[0].tzinfo) if getattr(last_full[0], 'tzinfo', None) else datetime.now()
    age_days = (now - last_full[0]).days
    if age_days >= 14:
        return "FULL", f"Letzte Vollsicherung ist {age_days} Tage alt – neue Vollprüfung empfohlen."
    if count >= 500 and age_days <= 3:
        return "QUICK", f"{count} Dateien und eine frische Vollsicherung – Schnellmodus spart Prüfzeit."
    if total >= 75 * 1024 * 1024 and age_days <= 2:
        return "QUICK", "Große Auswahl und sehr frische Vollsicherung – Schnellmodus empfohlen."
    return "INCREMENTAL", "Vollsicherung ist aktuell; neue/geänderte Dateien sicher per Hash prüfen."



def resolve_payload_target(requested: str, object_store_config: dict | None) -> tuple[str, object | None]:
    requested = (requested or "AUTO").upper()
    if requested not in {"AUTO", "NEON", "B2"}:
        raise ValueError("Ungültiges Speicherziel.")
    b2_store = make_b2_store(object_store_config)
    if requested == "B2" and b2_store is None:
        raise ValueError("Backblaze B2 ist noch nicht vollständig eingerichtet. Bitte im Zahnrad unter Dateispeicher einrichten und testen.")
    if requested == "AUTO":
        return ("B2", b2_store) if b2_store is not None else ("NEON", None)
    return requested, b2_store


def b2_usage_bytes(conn) -> int:
    row = conn.execute("SELECT COALESCE(sum(stored_bytes),0) FROM backup_vault.file_chunks WHERE storage_backend='B2'").fetchone()
    return int(row[0] or 0)

def _upload_worker_count(object_store_config: dict | None) -> int:
    """Bound B2 concurrency so backup speed improves without saturating the PC/network."""
    try:
        value = int((object_store_config or {}).get("upload_workers", 4))
    except Exception:
        value = 4
    return max(1, min(8, value))


def _upload_b2_file_worker(path: Path, comp: str, sha: str, key_b64: str, b2_store, control,
                           uploaded_keys: list[str], uploaded_lock: threading.Lock) -> dict:
    """Prepare/encrypt and upload one file. No database access occurs in worker threads."""
    chunks = []
    stored = 0
    raw_total = 0
    compression_saved = 0
    processing_seconds = 0.0
    request_seconds = 0.0
    peak_bps = 0.0
    chunk_no = 0
    with path.open("rb") as f:
        while True:
            _control_check(control)
            raw = f.read(B2_CHUNK_SIZE)
            if not raw:
                break
            t_proc = time.monotonic()
            payload = zlib.compress(raw, 6) if comp == "ZLIB" else raw
            compression_saved += max(0, len(raw) - len(payload))
            aad = f"{sha}:{chunk_no}".encode("ascii")
            nonce, cipher = encrypt_bytes(key_b64, payload, aad)
            cipher_hash = sha256_bytes(cipher)
            processing_seconds += max(0.0, time.monotonic() - t_proc)

            object_key = b2_store.object_key(sha, chunk_no)
            _control_check(control)
            t_req = time.monotonic()
            etag = b2_store.put(object_key, cipher, cipher_hash)
            req_elapsed = max(0.001, time.monotonic() - t_req)
            request_seconds += req_elapsed
            peak_bps = max(peak_bps, len(cipher) / req_elapsed)
            with uploaded_lock:
                uploaded_keys.append(object_key)
            chunks.append((chunk_no, nonce, cipher_hash, len(cipher), object_key, etag))
            stored += len(cipher)
            raw_total += len(raw)
            chunk_no += 1
            _control_check(control)
    return {
        "chunks": chunks,
        "stored": stored,
        "raw": raw_total,
        "compression_saved": compression_saved,
        "processing_seconds": processing_seconds,
        "request_seconds": request_seconds,
        "peak_bps": peak_bps,
    }


def backup_files(dsn: str, key_b64: str, profile: dict, config: dict, paths, progress=None,
                 trigger_type="MANUAL", plan_name=None, backup_mode="AUTO", payload_target="AUTO", object_store_config=None, control=None,
                 resume_from_job_id=None, recovery_hook=None):
    _control_check(control)
    if guard_active(config):
        raise ChristmasGuard("Weihnachtsmarkt-Schutzmodus ist aktiv (04.–13.12.). Neon-Backupzugriffe sind gesperrt.")
    if not paths:
        raise ValueError("Keine Dateien ausgewählt.")

    requested_mode = (backup_mode or "AUTO").upper()
    if requested_mode not in {"AUTO", "FULL", "INCREMENTAL", "QUICK"}:
        raise ValueError("Ungültige Sicherungsart.")
    if requested_mode == "AUTO":
        actual_mode, recommendation_reason = recommend_backup_mode(dsn, paths)
    else:
        actual_mode, recommendation_reason = requested_mode, "Vom Benutzer ausgewählt."

    actual_payload, b2_store = resolve_payload_target(payload_target, object_store_config)
    total_original = sum(p.stat().st_size for p in paths)
    max_run = int(config.get("max_run_mb", 100)) * 1024 * 1024
    if actual_payload == "NEON" and total_original > max_run:
        raise LimitBlocked(
            f"Neon-Kleinbackup: Auswahl ist {total_original/1024/1024:.1f} MB groß. "
            f"Maximal {max_run/1024/1024:.0f} MB pro Lauf. Für größere Sicherungen Backblaze B2 wählen/einrichten."
        )

    soft = int(profile.get("soft_limit_mb", 350)) * 1024 * 1024
    hard = int(profile.get("hard_limit_mb", 420)) * 1024 * 1024
    retention_days = max(1, int(config.get("retention_days", 90)))
    keep_last_versions = max(1, int(config.get("keep_last_versions", 10)))
    started_at = datetime.now().astimezone()
    started_mono = time.monotonic()
    directory_count = len({str(p.parent) for p in paths})
    largest_file_bytes = max((p.stat().st_size for p in paths), default=0)
    scan_started = time.monotonic()

    _control_check(control)
    activity("neon", "backup")
    with psycopg.connect(dsn) as conn:
        db_size = int(conn.execute("SELECT pg_database_size(current_database())").fetchone()[0])
        estimated, pre = 0, []
        skipped_count = 0
        scan_done = 0

        for idx, p in enumerate(paths, start=1):
            _control_check(control)
            stat = p.stat()
            _emit_progress(
                progress, idx - 1, len(paths), f"{actual_mode}: prüfe {p.name}",
                phase="Prüfung / Hash", bytes_done=scan_done, bytes_total=total_original,
                transfer_bytes=0, current_file=p.name, elapsed=_active_elapsed(control, started_mono),
            )
            try:
                logical = logical_path_hmac(key_b64, str(p.resolve()))
            except Exception:
                logical = logical_path_hmac(key_b64, str(p))

            previous = conn.execute(
                """
                SELECT content_sha256,original_size,modified_at,status
                FROM backup_vault.files
                WHERE logical_path_hmac=%s AND status IN ('STORED','DEDUPED')
                ORDER BY created_at DESC LIMIT 1
                """,
                (logical,),
            ).fetchone()

            if actual_mode == "QUICK" and previous:
                prev_hash, prev_size, prev_modified, _ = previous
                same_time = False
                if prev_modified is not None:
                    try:
                        same_time = abs(prev_modified.timestamp() - stat.st_mtime) < 1.0
                    except Exception:
                        same_time = False
                if int(prev_size or -1) == int(stat.st_size) and same_time:
                    skipped_count += 1
                    pre.append((p, "NONE", None, False, logical, "SKIP"))
                    scan_done += stat.st_size
                    _emit_progress(
                        progress, idx, len(paths), f"Unverändert geprüft: {p.name}",
                        phase="Prüfung / Hash", bytes_done=scan_done, bytes_total=total_original,
                        transfer_bytes=0, current_file=p.name, elapsed=_active_elapsed(control, started_mono),
                    )
                    continue

            comp = choose_compression(p)
            base_done = scan_done
            sha = file_sha256(
                p,
                lambda file_done, _idx=idx, _p=p, _base=base_done: _emit_progress(
                    progress, _idx - 1, len(paths), f"Prüfe Inhalt: {_p.name}",
                    phase="Prüfung / Hash", bytes_done=min(total_original, _base + file_done),
                    bytes_total=total_original, transfer_bytes=0, current_file=_p.name,
                    elapsed=_active_elapsed(control, started_mono),
                ),
                control=control,
            )
            scan_done += stat.st_size

            if actual_mode == "INCREMENTAL" and previous and previous[0] == sha:
                skipped_count += 1
                pre.append((p, comp, sha, False, logical, "SKIP"))
                _emit_progress(
                    progress, idx, len(paths), f"Unverändert geprüft: {p.name}",
                    phase="Prüfung / Hash", bytes_done=scan_done, bytes_total=total_original,
                    transfer_bytes=0, current_file=p.name, elapsed=_active_elapsed(control, started_mono),
                )
                continue

            exists = conn.execute(
                "SELECT id FROM backup_vault.files WHERE sha256=%s AND status='STORED' AND payload_backend=%s ORDER BY created_at DESC LIMIT 1",
                (sha, actual_payload),
            ).fetchone()
            estimated += 0 if exists else estimate_payload(p, comp)
            pre.append((p, comp, sha, exists is not None, logical, "STORE"))
            _emit_progress(
                progress, idx, len(paths), f"Geprüft: {p.name}",
                phase="Prüfung / Hash", bytes_done=scan_done, bytes_total=total_original,
                transfer_bytes=0, current_file=p.name, elapsed=_active_elapsed(control, started_mono),
            )

        scan_duration_seconds = max(0.0, time.monotonic() - scan_started)
        _control_check(control)
        if actual_payload == "NEON":
            if db_size + estimated > hard:
                raise LimitBlocked(
                    f"Neon-Kapazitätsschutz: aktuell {db_size/1024/1024:.1f} MB + geschätzt "
                    f"{estimated/1024/1024:.1f} MB > Hardlimit {hard/1024/1024:.0f} MB. "
                    "Für große Dateidaten Backblaze B2 verwenden."
                )
        else:
            b2_cfg = dict(object_store_config or {})
            b2_hard = max(1.0, float(b2_cfg.get("hard_limit_gb", 10))) * 1024 * 1024 * 1024
            current_b2 = b2_usage_bytes(conn)
            if current_b2 + estimated > b2_hard:
                raise LimitBlocked(
                    f"B2-Kostenschutz: verwaltet {current_b2/1024/1024/1024:.2f} GB + geschätzt "
                    f"{estimated/1024/1024/1024:.2f} GB > eingestelltes Hardlimit {b2_hard/1024/1024/1024:.1f} GB."
                )
            if db_size >= hard:
                raise LimitBlocked(
                    f"Neon-Core ist mit {db_size/1024/1024:.1f} MB am Hardlimit. "
                    "Auch bei B2-Dateispeicher werden Metadaten in Neon benötigt."
                )

        changed_count = sum(1 for item in pre if item[5] == "STORE")
        worker_count = _upload_worker_count(object_store_config) if actual_payload == "B2" else 1
        job_id = conn.execute(
            """
            INSERT INTO backup_vault.backup_jobs
            (started_at,status,app_version,trigger_type,plan_name,backup_mode,scanned_count,changed_count,skipped_count,
             retention_until,payload_target,directory_count,largest_file_bytes,original_bytes,scan_duration_seconds,upload_worker_count,
             recovery_state,resume_from_job_id)
            VALUES (%s,'RUNNING',%s,%s,%s,%s,%s,%s,%s,now()+(%s || ' days')::interval,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id
            """,
            (started_at, config.get("app_version", "1.7.0"), trigger_type, plan_name, actual_mode,
             len(paths), changed_count, skipped_count, retention_days, actual_payload, directory_count,
             largest_file_bytes, total_original, scan_duration_seconds, worker_count,
             "RESUMED" if resume_from_job_id else "NONE", resume_from_job_id),
        ).fetchone()[0]
        record_usage_snapshot(conn, hard)
        activity("neon", "commit")
        conn.commit()
        if recovery_hook:
            try: recovery_hook("job_created", {"job_id": str(job_id), "resume_from_job_id": str(resume_from_job_id or "")})
            except Exception: pass

        stored_total = dedup_total = ok_count = 0
        compression_saved_total = 0
        peak_transfer_bps = 0.0
        new_chunk_count = 0
        logical_hmacs = []
        processing_seconds_total = 0.0
        b2_request_seconds_total = 0.0
        metadata_seconds_total = 0.0
        upload_stage_seconds = 0.0
        uploaded_keys: list[str] = []
        uploaded_lock = threading.Lock()

        def cleanup_uploaded_objects():
            cleanup_errors = []
            if actual_payload != "B2" or b2_store is None:
                return cleanup_errors
            keys = set()
            with uploaded_lock:
                keys.update(uploaded_keys)
            try:
                rows = conn.execute(
                    """SELECT c.object_key FROM backup_vault.file_chunks c
                       JOIN backup_vault.files f ON f.id=c.file_id
                       WHERE f.job_id=%s AND c.storage_backend='B2' AND c.object_key IS NOT NULL""",
                    (job_id,),
                ).fetchall()
                keys.update(r[0] for r in rows if r and r[0])
            except Exception as exc:
                cleanup_errors.append(f"B2-Cleanup-Liste: {exc}")
            for key in keys:
                try:
                    b2_store.delete(key)
                except Exception as exc:
                    cleanup_errors.append(f"{key}: {exc}")
            return cleanup_errors

        def rollback_cancelled_job():
            cleanup_errors = cleanup_uploaded_objects()
            try:
                if cleanup_errors:
                    conn.execute("UPDATE backup_vault.files SET status='FAILED',retention_until=now() WHERE job_id=%s", (job_id,))
                else:
                    conn.execute("UPDATE backup_vault.files SET retention_until=now() WHERE job_id=%s", (job_id,))
                    conn.execute("DELETE FROM backup_vault.files WHERE job_id=%s", (job_id,))
                note = "Vom Benutzer abgebrochen; unvollständiger Lauf zurückgerollt."
                if cleanup_errors:
                    note += " B2-Cleanup unvollständig: " + " | ".join(cleanup_errors[:3])
                conn.execute(
                    """UPDATE backup_vault.backup_jobs
                       SET finished_at=now(),status='CANCELLED',file_count=0,stored_bytes=0,deduplicated_bytes=0,
                           active_duration_seconds=%s,scan_duration_seconds=%s,upload_stage_seconds=%s,
                           processing_seconds=%s,b2_request_seconds=%s,metadata_seconds=%s,note=%s
                       WHERE id=%s""",
                    (_active_elapsed(control, started_mono), scan_duration_seconds, upload_stage_seconds,
                     processing_seconds_total, b2_request_seconds_total, metadata_seconds_total, note[:1000], job_id),
                )
                record_usage_snapshot(conn, hard)
                activity("neon", "commit")
                conn.commit()
                return cleanup_errors
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
                raise

        try:
            work_done = sum(p.stat().st_size for p, _, _, _, _, action in pre if action == "SKIP")
            transfer_done = 0
            pending_b2 = []
            meta_started = time.monotonic()

            # Create all file rows first. This removes one network commit before every B2 upload.
            for idx, (path, comp, sha, is_dup, logical_hmac, action) in enumerate(pre, start=1):
                _control_check(control)
                logical_hmacs.append(logical_hmac)
                stat = path.stat()
                if action == "SKIP":
                    continue
                file_id = conn.execute(
                    """
                    INSERT INTO backup_vault.files
                    (job_id, original_path, file_name, extension, mime_type, modified_at,
                     original_size, sha256, content_sha256, compression, status, logical_path_hmac, retention_until, payload_backend)
                    VALUES (%s,%s,%s,%s,%s,to_timestamp(%s),%s,%s,%s,%s,%s,%s,now()+(%s || ' days')::interval,%s)
                    RETURNING id
                    """,
                    (
                        job_id, encrypt_text(key_b64, str(path.parent)), encrypt_text(key_b64, path.name), path.suffix.lower(),
                        mimetypes.guess_type(path.name)[0], stat.st_mtime, stat.st_size, sha, sha, comp,
                        "DEDUPED" if is_dup else "PENDING", logical_hmac, retention_days, actual_payload,
                    ),
                ).fetchone()[0]
                if is_dup:
                    dedup_total += stat.st_size
                    ok_count += 1
                    work_done += stat.st_size
                elif actual_payload == "B2":
                    pending_b2.append((idx, file_id, path, comp, sha, stat.st_size))
                else:
                    # Neon payload remains deliberately sequential and is only for small backups.
                    stored = chunk_no = 0
                    with path.open("rb") as f:
                        while True:
                            _control_check(control)
                            raw = f.read(CHUNK_SIZE)
                            if not raw:
                                break
                            t_proc = time.monotonic()
                            payload = zlib.compress(raw, 6) if comp == "ZLIB" else raw
                            compression_saved_total += max(0, len(raw) - len(payload))
                            aad = f"{sha}:{chunk_no}".encode("ascii")
                            nonce, cipher = encrypt_bytes(key_b64, payload, aad)
                            cipher_hash = sha256_bytes(cipher)
                            processing_seconds_total += max(0.0, time.monotonic() - t_proc)
                            t_db = time.monotonic()
                            conn.execute(
                                """INSERT INTO backup_vault.file_chunks
                                   (file_id,chunk_no,nonce,encrypted_data,chunk_sha256,stored_bytes,storage_backend)
                                   VALUES (%s,%s,%s,%s,%s,%s,'NEON')""",
                                (file_id, chunk_no, nonce, cipher, cipher_hash, len(cipher)),
                            )
                            metadata_seconds_total += max(0.0, time.monotonic() - t_db)
                            stored += len(cipher); transfer_done += len(cipher); work_done += len(raw)
                            chunk_no += 1; new_chunk_count += 1
                    conn.execute("UPDATE backup_vault.files SET stored_size=%s,chunk_count=%s,status='STORED' WHERE id=%s", (stored,chunk_no,file_id))
                    stored_total += stored; ok_count += 1
            activity("neon", "commit")
            conn.commit()
            metadata_seconds_total += max(0.0, time.monotonic() - meta_started)

            if actual_payload == "B2" and pending_b2:
                actual_workers = max(1, min(worker_count, len(pending_b2)))
                upload_started = time.monotonic()
                _emit_progress(
                    progress, ok_count + skipped_count, len(paths),
                    f"B2-Pipeline startet mit {actual_workers} parallelen Uploads …",
                    phase=f"B2-Upload ({actual_workers} parallel)", bytes_done=work_done, bytes_total=total_original,
                    transfer_bytes=transfer_done, current_file="", elapsed=_active_elapsed(control, started_mono),
                )
                executor = ThreadPoolExecutor(max_workers=actual_workers, thread_name_prefix="pcbv-b2")
                futures = {}
                try:
                    for idx, file_id, path, comp, sha, original_size in pending_b2:
                        _control_check(control)
                        fut = executor.submit(
                            _upload_b2_file_worker, path, comp, sha, key_b64, b2_store, control,
                            uploaded_keys, uploaded_lock,
                        )
                        futures[fut] = (idx, file_id, path, original_size)

                    completed = 0
                    for fut in as_completed(futures):
                        _control_check(control)
                        idx, file_id, path, original_size = futures[fut]
                        result = fut.result()
                        t_meta = time.monotonic()
                        if result["chunks"]:
                            # psycopg 3 exposes executemany() on Cursor, not Connection.
                            # Keep all DB writes on the main thread while B2 workers only upload payloads.
                            with conn.cursor() as cur:
                                cur.executemany(
                                    """INSERT INTO backup_vault.file_chunks
                                       (file_id,chunk_no,nonce,encrypted_data,chunk_sha256,stored_bytes,storage_backend,object_key,object_etag)
                                       VALUES (%s,%s,%s,NULL,%s,%s,'B2',%s,%s)""",
                                    [(file_id, no, nonce, chash, sz, key, etag) for no, nonce, chash, sz, key, etag in result["chunks"]],
                                )
                        conn.execute(
                            "UPDATE backup_vault.files SET stored_size=%s,chunk_count=%s,status='STORED' WHERE id=%s",
                            (result["stored"], len(result["chunks"]), file_id),
                        )
                        # Commit every completed file: crash durability is kept while the upload stage is parallel.
                        activity("neon", "commit")
                        conn.commit()
                        metadata_seconds_total += max(0.0, time.monotonic() - t_meta)
                        stored_total += result["stored"]
                        transfer_done += result["stored"]
                        work_done += result["raw"]
                        compression_saved_total += result["compression_saved"]
                        processing_seconds_total += result["processing_seconds"]
                        b2_request_seconds_total += result["request_seconds"]
                        peak_transfer_bps = max(peak_transfer_bps, result["peak_bps"])
                        new_chunk_count += len(result["chunks"])
                        ok_count += 1
                        completed += 1
                        _emit_progress(
                            progress, min(len(paths), skipped_count + ok_count), len(paths), f"Gesichert: {path.name}",
                            phase=f"B2-Upload ({actual_workers} parallel)", bytes_done=min(total_original, work_done),
                            bytes_total=total_original, transfer_bytes=transfer_done, current_file=path.name,
                            elapsed=_active_elapsed(control, started_mono),
                        )
                except Exception:
                    if control is not None:
                        control.cancel()
                    for f in futures:
                        f.cancel()
                    raise
                finally:
                    executor.shutdown(wait=True, cancel_futures=True)
                    upload_stage_seconds = max(0.0, time.monotonic() - upload_started)

            _control_check(control)
            final_elapsed = _active_elapsed(control, started_mono)
            t_meta = time.monotonic()
            conn.execute(
                """
                UPDATE backup_vault.backup_jobs
                SET finished_at=now(),status='SUCCESS',file_count=%s,original_bytes=%s,
                    stored_bytes=%s,deduplicated_bytes=%s,scanned_count=%s,changed_count=%s,skipped_count=%s,
                    active_duration_seconds=%s,avg_speed_bps=%s,peak_transfer_bps=%s,compression_saved_bytes=%s,chunk_count=%s,
                    directory_count=%s,largest_file_bytes=%s,scan_duration_seconds=%s,upload_stage_seconds=%s,
                    processing_seconds=%s,b2_request_seconds=%s,metadata_seconds=%s,upload_worker_count=%s,
                    recovery_state=%s,resumed_file_count=%s
                WHERE id=%s
                """,
                (ok_count, total_original, stored_total, dedup_total, len(paths), changed_count, skipped_count,
                 final_elapsed, int(total_original / max(0.001, final_elapsed)), int(peak_transfer_bps),
                 compression_saved_total, new_chunk_count, directory_count, largest_file_bytes, scan_duration_seconds,
                 upload_stage_seconds, processing_seconds_total, b2_request_seconds_total, metadata_seconds_total,
                 worker_count, "RESUMED" if resume_from_job_id else "NONE", skipped_count if resume_from_job_id else 0, job_id),
            )
            if resume_from_job_id:
                conn.execute(
                    """UPDATE backup_vault.backup_jobs
                       SET recovery_state='RESUMED', resumed_by_job_id=%s
                       WHERE id=%s AND status='INTERRUPTED'""",
                    (job_id, resume_from_job_id),
                )
            mark_cleanup_eligibility(conn, logical_hmacs, keep_last_versions)
            record_usage_snapshot(conn, hard)
            activity("neon", "commit")
            conn.commit()
            metadata_seconds_total += max(0.0, time.monotonic() - t_meta)
            if recovery_hook:
                try: recovery_hook("success", {"job_id": str(job_id), "resumed_file_count": skipped_count if resume_from_job_id else 0})
                except Exception: pass
            return {
                "job_id": str(job_id), "status": "SUCCESS", "mode": actual_mode, "payload_target": actual_payload,
                "recommendation_reason": recommendation_reason, "files": ok_count, "scanned": len(paths),
                "changed": changed_count, "skipped": skipped_count, "original_bytes": total_original,
                "stored_bytes": stored_total, "dedup_bytes": dedup_total,
                "compression_saved_bytes": compression_saved_total, "chunk_count": new_chunk_count,
                "directory_count": directory_count, "largest_file_bytes": largest_file_bytes,
                "duration_seconds": final_elapsed, "avg_speed_bps": int(total_original / max(0.001, final_elapsed)),
                "peak_transfer_bps": int(peak_transfer_bps), "warn_soft": (db_size + stored_total) >= soft,
                "scan_duration_seconds": scan_duration_seconds, "upload_stage_seconds": upload_stage_seconds,
                "processing_seconds": processing_seconds_total, "b2_request_seconds": b2_request_seconds_total,
                "metadata_seconds": metadata_seconds_total, "upload_worker_count": worker_count,
            }
        except BackupCancelled:
            rollback_cancelled_job()
            raise
        except Exception as e:
            cleanup_errors = cleanup_uploaded_objects()
            try:
                conn.execute("UPDATE backup_vault.files SET status='FAILED',retention_until=now() WHERE job_id=%s AND status='PENDING'", (job_id,))
                note = str(e)
                if cleanup_errors:
                    note += " | B2-Cleanup unvollständig: " + " | ".join(cleanup_errors[:3])
                conn.execute(
                    """UPDATE backup_vault.backup_jobs SET finished_at=now(),status='FAILED',active_duration_seconds=%s,
                       scan_duration_seconds=%s,upload_stage_seconds=%s,processing_seconds=%s,b2_request_seconds=%s,
                       metadata_seconds=%s,note=%s WHERE id=%s""",
                    (_active_elapsed(control, started_mono), scan_duration_seconds, upload_stage_seconds,
                     processing_seconds_total, b2_request_seconds_total, metadata_seconds_total, note[:1000], job_id),
                )
                record_usage_snapshot(conn, hard)
                activity("neon", "commit")
                conn.commit()
            except Exception:
                pass
            raise

def _safe_output(root: Path, relative: Path) -> Path:
    clean = []
    for part in relative.parts:
        if part in ("", ".", "..", "/", "\\"):
            continue
        part = part.replace(":", "")
        clean.append(part)
    candidate = root.joinpath(*clean)
    root_resolved = root.resolve()
    candidate.parent.mkdir(parents=True, exist_ok=True)
    if root_resolved not in candidate.resolve().parents and candidate.resolve() != root_resolved:
        raise ValueError("Ungültiger Wiederherstellungspfad.")
    return candidate


def restore_file(dsn: str, key_b64: str, file_id: str, destination: Path, relative_path: Path | None = None, object_store_config=None) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    activity("neon", "backup")
    with psycopg.connect(dsn) as conn:
        row = conn.execute("SELECT id,file_name,sha256,compression,status,original_size,job_id,payload_backend FROM backup_vault.files WHERE id=%s", (file_id,)).fetchone()
        if not row:
            raise ValueError("Datei nicht gefunden.")
        fid, enc_name, sha, comp, status, original_size, job_id, payload_backend = row
        source_id = fid
        source_comp = comp
        source_backend = payload_backend or "NEON"
        if status == "DEDUPED":
            c = conn.execute("SELECT id,compression,payload_backend FROM backup_vault.files WHERE sha256=%s AND status='STORED' AND payload_backend=%s ORDER BY created_at ASC LIMIT 1", (sha, source_backend)).fetchone()
            if not c:
                raise ValueError("Duplikatquelle nicht gefunden.")
            source_id, source_comp, source_backend = c
        name = decrypt_text(key_b64, enc_name)
        out = _safe_output(destination, relative_path if relative_path is not None else Path(name))
        if out.exists():
            base = out.with_suffix("") if out.suffix else out
            suffix = out.suffix
            n = 1
            while out.exists():
                out = Path(str(base) + f"_restore_{n}" + suffix)
                n += 1
        tmp = out.with_suffix(out.suffix + ".part")
        h = hashlib.sha256()
        total = 0
        try:
            with tmp.open("wb") as f:
                chunks = conn.execute("SELECT chunk_no,nonce,encrypted_data,chunk_sha256,storage_backend,object_key FROM backup_vault.file_chunks WHERE file_id=%s ORDER BY chunk_no", (source_id,)).fetchall()
                b2_restore = make_b2_store(object_store_config) if source_backend == "B2" else None
                if source_backend == "B2" and b2_restore is None:
                    raise ValueError("Diese Sicherung liegt in Backblaze B2, aber B2 ist lokal nicht eingerichtet.")
                for chunk_no, nonce, cipher, expected, storage_backend, object_key in chunks:
                    if (storage_backend or source_backend) == "B2":
                        cipher = b2_restore.get(object_key)
                    else:
                        cipher = bytes(cipher)
                    if sha256_bytes(cipher) != expected:
                        raise ValueError(f"Chunk {chunk_no}: Hashfehler.")
                    payload = decrypt_bytes(key_b64, bytes(nonce), cipher, f"{sha}:{chunk_no}".encode("ascii"))
                    raw = zlib.decompress(payload) if source_comp == "ZLIB" else payload
                    f.write(raw)
                    h.update(raw)
                    total += len(raw)
            if h.hexdigest() != sha or total != original_size:
                raise ValueError("Hash oder Größe stimmt nicht.")
            tmp.replace(out)
            conn.execute("INSERT INTO backup_vault.restore_tests(job_id,file_id,result,hash_match,restored_bytes,details) VALUES (%s,%s,'PASS',true,%s,'Restore and SHA-256 verification successful')", (job_id, fid, total))
            activity("neon", "commit")
            conn.commit()
            return out
        except Exception as e:
            tmp.unlink(missing_ok=True)
            conn.execute("INSERT INTO backup_vault.restore_tests(job_id,file_id,result,hash_match,restored_bytes,details) VALUES (%s,%s,'FAIL',false,%s,%s)", (job_id, fid, total, str(e)[:500]))
            activity("neon", "commit")
            conn.commit()
            raise ValueError(f"Wiederherstellung fehlgeschlagen: {e}")
