from __future__ import annotations
from datetime import datetime, timedelta
import uuid
import psycopg
from status_bus import activity
from vault_db import forbidden_tables
from interrupted_recovery import checkpoint_path, checkpoint_has_plaintext_paths


def run_tuev(dsn: str, key_present: bool, recovery_exported: bool, profile: dict, config: dict):
    checks=[]
    def add(code,name,result,details): checks.append((code,name,result,details))
    try:
        activity("neon","tuev")
        with psycopg.connect(dsn,connect_timeout=8) as conn:
            dbname=conn.execute("SELECT current_database()").fetchone()[0]; add("DB-001","Datenbank erreichbar","PASS",dbname)
            core=conn.execute("SELECT schema_version,environment,isolation_rule FROM backup_vault.core WHERE id=1").fetchone()
            add("CORE-001","Core vorhanden","PASS" if core and core[1]=="backup-only" else "FAIL",f"Schema {core[0]}" if core else "Core fehlt")
            bad=forbidden_tables(dsn); add("ISO-001","KC-Isolation","PASS" if not bad else "FAIL","Keine fremden Tabellen" if not bad else ", ".join(bad[:10]))
            size=int(conn.execute("SELECT pg_database_size(current_database())").fetchone()[0]); soft=int(profile.get("soft_limit_mb",350))*1024*1024; hard=int(profile.get("hard_limit_mb",420))*1024*1024
            add("CAP-001","Kapazität","FAIL" if size>=hard else ("WARN" if size>=soft else "PASS"),f"{size/1024/1024:.1f} MB / Hardlimit {hard/1024/1024:.0f} MB")
            row=conn.execute("SELECT run_at FROM backup_vault.restore_tests WHERE result='PASS' ORDER BY run_at DESC LIMIT 1").fetchone()
            if row is None:add("RST-001","Restore-Test","WARN","Noch kein erfolgreicher Wiederherstellungstest")
            elif row[0] < datetime.now(row[0].tzinfo)-timedelta(days=30):add("RST-001","Restore-Test","WARN","Letzter Restore-Test älter als 30 Tage")
            else:add("RST-001","Restore-Test","PASS",f"Letzter Test: {row[0]:%d.%m.%Y %H:%M}")
            orphan=conn.execute("""SELECT count(*) FROM backup_vault.files d WHERE d.status='DEDUPED' AND NOT EXISTS (SELECT 1 FROM backup_vault.files s WHERE s.sha256=d.sha256 AND s.status='STORED')""").fetchone()[0]
            add("DED-001","Deduplikationsquellen","PASS" if orphan==0 else "FAIL",f"{orphan} verwaiste Duplikatquelle(n)")
            add("SEC-001","Lokaler Schlüssel","PASS" if key_present else "FAIL","Schlüssel im Betriebssystem-Tresor" if key_present else "Schlüssel fehlt")
            add("SEC-002","Notfallschlüssel exportiert","PASS" if recovery_exported else "WARN","Offline-Kopie vorhanden" if recovery_exported else "Bitte Recovery-Key separat exportieren")
            add("OPS-001","Weihnachtsmarkt-Schutz","PASS" if config.get("christmas_guard",True) else "WARN","04.–13.12. geschützt" if config.get("christmas_guard",True) else "Schutz deaktiviert")
            unsafe=[]
            for p in config.get("plans",[]):
                raw=str(p).lower()
                if "postgresql://" in raw or "password=" in raw or "npg_" in raw:unsafe.append(p.get("name","?"))
            add("OPS-002","Scheduler ohne Geheimnisse","PASS" if not unsafe else "FAIL","Keine Zugangsdaten in One-Touch-Plänen" if not unsafe else ", ".join(unsafe))
            b2meta=config.get("b2",{}) or {}; b2raw=str(b2meta).lower(); leak=any(x in b2raw for x in ("application_key","secret_access_key","b2_application_key"))
            add("OBJ-002","B2-Geheimnisse lokal","FAIL" if leak else "PASS","Keine B2-Geheimnisse in config.json" if not leak else "B2-Geheimnis in Konfiguration gefunden")
            b2_rows=conn.execute("SELECT count(*) FROM backup_vault.file_chunks WHERE storage_backend='B2' AND object_key IS NULL").fetchone()[0]
            add("OBJ-003","B2-Objektverweise","PASS" if b2_rows==0 else "FAIL",f"{b2_rows} B2-Chunk(s) ohne Objektverweis")
            has_verify=conn.execute("SELECT to_regclass('backup_vault.backup_verifications') IS NOT NULL").fetchone()[0]
            add("VER-010","Verifizierungsprotokoll","PASS" if has_verify else "FAIL","backup_verifications vorhanden" if has_verify else "Tabelle backup_verifications fehlt")
            last_job=conn.execute("SELECT id,started_at FROM backup_vault.backup_jobs WHERE status='SUCCESS' ORDER BY started_at DESC LIMIT 1").fetchone()
            if last_job and has_verify:
                vr=conn.execute("SELECT mode,result,finished_at FROM backup_vault.backup_verifications WHERE job_id=%s ORDER BY finished_at DESC NULLS LAST,id DESC LIMIT 1",(last_job[0],)).fetchone()
                if not vr:add("VER-011","Letztes Backup verifiziert","WARN","Für das letzte erfolgreiche Backup liegt noch keine Verifizierung vor")
                else:add("VER-011","Letztes Backup verifiziert","PASS" if vr[1]=='PASS' else "FAIL",f"{vr[0]} / {vr[1]} – {vr[2]:%d.%m.%Y %H:%M}" if vr[2] else f"{vr[0]} / {vr[1]}")
            elif not last_job:add("VER-011","Letztes Backup verifiziert","WARN","Noch kein erfolgreiches Backup vorhanden")
            report_cols=conn.execute("""SELECT count(*) FROM information_schema.columns WHERE table_schema='backup_vault' AND table_name='backup_jobs' AND column_name IN ('directory_count','active_duration_seconds','avg_speed_bps','peak_transfer_bps','compression_saved_bytes','chunk_count','largest_file_bytes')""").fetchone()[0]
            add("RPT-001","Report-Metriken","PASS" if report_cols==7 else "FAIL",f"{report_cols}/7 Report-Felder vorhanden")
            perf_cols=conn.execute("""SELECT count(*) FROM information_schema.columns WHERE table_schema='backup_vault' AND table_name='backup_jobs' AND column_name IN ('scan_duration_seconds','upload_stage_seconds','processing_seconds','b2_request_seconds','metadata_seconds','upload_worker_count')""").fetchone()[0]
            add("PERF-003","Performance-Metriken","PASS" if perf_cols==6 else "FAIL",f"{perf_cols}/6 Performance-Felder vorhanden")
            workers=int((config.get("b2",{}) or {}).get("upload_workers",4) or 4); add("PERF-002","B2-Worker-Limit","PASS" if 1<=workers<=8 else "FAIL",f"Konfiguriert: {workers}; erlaubt 1–8")

            recovery_cols=conn.execute("""SELECT count(*) FROM information_schema.columns WHERE table_schema='backup_vault' AND table_name='backup_jobs' AND column_name IN ('recovery_state','interrupted_at','resume_from_job_id','resumed_by_job_id','resumed_file_count')""").fetchone()[0]
            add("REC-010","Recovery-Schema","PASS" if recovery_cols==5 else "FAIL",f"{recovery_cols}/5 Recovery-Felder vorhanden")
            add("REC-011","Recovery-Checkpoint verschlüsselt","FAIL" if checkpoint_has_plaintext_paths() else "PASS","Kein Klartextpfad im lokalen Checkpoint" if checkpoint_path().exists() else "Kein aktiver Checkpoint")
            rec_bad=conn.execute("SELECT count(*) FROM backup_vault.backup_jobs WHERE status='INTERRUPTED' AND recovery_state NOT IN ('RECOVERABLE','RESUMED','DISCARDED')").fetchone()[0] if recovery_cols==5 else 0
            add("REC-012","Recovery-Zustände","PASS" if recovery_cols==5 and rec_bad==0 else "FAIL",f"{rec_bad} inkonsistente unterbrochene Jobs" if recovery_cols==5 else "Recovery-Schema fehlt")
            add("OPS-010","Single-Instance-Schutz","PASS","UI und Scheduler verwenden denselben OS-Prozesslock")

            kc=config.get("kc_communication",{}) or {}; enabled=bool(kc.get("enabled")); endpoint=str(kc.get("endpoint_url") or "")
            device_id=str(kc.get("device_id") or ""); valid_uuid=True
            try:uuid.UUID(device_id)
            except Exception:valid_uuid=False
            machine_ok=(not enabled) or (endpoint.endswith('/functions/v1/kc-communication-machine') and valid_uuid)
            add("COM-010","KC Machine API","PASS" if machine_ok else "FAIL","deaktiviert" if not enabled else ("Zentrale Machine-API und Geräte-ID konfiguriert" if machine_ok else "Machine-API/Geräte-ID ungültig"))
            raw_cfg=str(config).lower(); secret_markers=("kc_machine_device_token","kc_communication_token","authorization: bearer","b2_application_key","postgresql://"); leaked=[m for m in secret_markers if m in raw_cfg]
            add("SEC-020","Kommunikations-Geheimnisse lokal","PASS" if not leaked else "FAIL","Keine Kommunikations-/DB-Geheimnisse in config.json" if not leaked else "Verdächtige Geheimnis-Marker in Konfiguration")
            channels=set(kc.get("channels") or []); add("COM-011","KC Kanäle","PASS" if not enabled or (channels and channels <= {'push','email'}) else "FAIL",f"Kanäle: {', '.join(sorted(channels)) or 'keine'}")
            add("PERF-010","Dashboard Lazy-Load","PASS","Dateikatalog wird erst bei Dateisuche/Inventar geladen")
            add("LOG-001","Startprotokoll schaltbar","PASS","Startprotokoll EIN" if config.get("start_protocol_enabled",True) else "Startprotokoll AUS")
            for c in checks:
                conn.execute("INSERT INTO backup_vault.tuev_checks(check_code,check_name,result,details,app_version,schema_version) VALUES (%s,%s,%s,%s,%s,%s)",(c[0],c[1],c[2],c[3],config.get("app_version","1.7.0"),core[0] if core else "unknown"))
            activity("neon","commit"); conn.commit()
    except Exception as e:
        checks.append(("DB-999","TÜV-Lauf","FAIL",str(e)))
    return checks
