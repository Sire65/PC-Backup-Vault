CREATE SCHEMA IF NOT EXISTS backup_vault;

CREATE TABLE IF NOT EXISTS backup_vault.core (
  id smallint PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  product_name text NOT NULL DEFAULT 'PC Backup Vault',
  schema_version text NOT NULL DEFAULT '1.7.0',
  app_min_version text NOT NULL DEFAULT '1.7.0',
  environment text NOT NULL DEFAULT 'backup-only',
  isolation_rule text NOT NULL DEFAULT 'NO_KC_MIRRORING_NO_KC_TABLES_NO_SHARED_CREDENTIALS',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE OR REPLACE FUNCTION backup_vault.prevent_core_version_downgrade()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  old_schema int[];
  new_schema int[];
  old_app int[];
  new_app int[];
BEGIN
  old_schema := string_to_array(OLD.schema_version, '.')::int[];
  new_schema := string_to_array(NEW.schema_version, '.')::int[];
  old_app := string_to_array(OLD.app_min_version, '.')::int[];
  new_app := string_to_array(NEW.app_min_version, '.')::int[];

  IF new_schema < old_schema THEN
    RAISE EXCEPTION 'Core-Downgrade blockiert: % -> %', OLD.schema_version, NEW.schema_version;
  END IF;
  IF new_app < old_app THEN
    RAISE EXCEPTION 'App-Mindestversion-Downgrade blockiert: % -> %', OLD.app_min_version, NEW.app_min_version;
  END IF;
  RETURN NEW;
END;
$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger
    WHERE tgname='trg_prevent_core_version_downgrade'
      AND tgrelid='backup_vault.core'::regclass
      AND NOT tgisinternal
  ) THEN
    CREATE TRIGGER trg_prevent_core_version_downgrade
      BEFORE UPDATE ON backup_vault.core
      FOR EACH ROW
      EXECUTE FUNCTION backup_vault.prevent_core_version_downgrade();
  END IF;
END $$;

INSERT INTO backup_vault.core (id,schema_version,app_min_version) VALUES (1,'1.7.0','1.7.0')
ON CONFLICT (id) DO UPDATE SET schema_version='1.7.0',app_min_version='1.7.0',updated_at=now();

CREATE TABLE IF NOT EXISTS backup_vault.storage_targets (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  display_name text NOT NULL,
  provider text NOT NULL CHECK (provider IN ('neon','supabase','postgresql')),
  host_hint text,
  database_name text,
  project_ref text,
  enabled boolean NOT NULL DEFAULT true,
  is_primary boolean NOT NULL DEFAULT false,
  soft_limit_mb integer NOT NULL DEFAULT 350 CHECK (soft_limit_mb > 0),
  hard_limit_mb integer NOT NULL DEFAULT 420 CHECK (hard_limit_mb >= soft_limit_mb),
  credentials_location text NOT NULL DEFAULT 'LOCAL_OS_KEYRING',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS backup_vault.backup_jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  target_id uuid REFERENCES backup_vault.storage_targets(id),
  started_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  status text NOT NULL CHECK (status IN ('RUNNING','SUCCESS','PARTIAL','FAILED','CANCELLED','BLOCKED_LIMIT')),
  file_count integer NOT NULL DEFAULT 0,
  original_bytes bigint NOT NULL DEFAULT 0,
  stored_bytes bigint NOT NULL DEFAULT 0,
  deduplicated_bytes bigint NOT NULL DEFAULT 0,
  compression_mode text NOT NULL DEFAULT 'AUTO',
  encryption_mode text NOT NULL DEFAULT 'AES-256-GCM',
  note text,
  app_version text,
  trigger_type text NOT NULL DEFAULT 'MANUAL',
  plan_name text,
  retention_until timestamptz,
  payload_target text NOT NULL DEFAULT 'NEON',
  directory_count integer NOT NULL DEFAULT 0,
  active_duration_seconds numeric(14,3) NOT NULL DEFAULT 0,
  avg_speed_bps bigint NOT NULL DEFAULT 0,
  peak_transfer_bps bigint NOT NULL DEFAULT 0,
  compression_saved_bytes bigint NOT NULL DEFAULT 0,
  chunk_count integer NOT NULL DEFAULT 0,
  largest_file_bytes bigint NOT NULL DEFAULT 0,
  scan_duration_seconds numeric(14,3) NOT NULL DEFAULT 0,
  upload_stage_seconds numeric(14,3) NOT NULL DEFAULT 0,
  processing_seconds numeric(14,3) NOT NULL DEFAULT 0,
  b2_request_seconds numeric(14,3) NOT NULL DEFAULT 0,
  metadata_seconds numeric(14,3) NOT NULL DEFAULT 0,
  upload_worker_count integer NOT NULL DEFAULT 1
);
ALTER TABLE backup_vault.backup_jobs ADD COLUMN IF NOT EXISTS trigger_type text NOT NULL DEFAULT 'MANUAL';
ALTER TABLE backup_vault.backup_jobs ADD COLUMN IF NOT EXISTS plan_name text;
ALTER TABLE backup_vault.backup_jobs ADD COLUMN IF NOT EXISTS backup_mode text NOT NULL DEFAULT 'AUTO';
ALTER TABLE backup_vault.backup_jobs ADD COLUMN IF NOT EXISTS scanned_count integer NOT NULL DEFAULT 0;
ALTER TABLE backup_vault.backup_jobs ADD COLUMN IF NOT EXISTS changed_count integer NOT NULL DEFAULT 0;
ALTER TABLE backup_vault.backup_jobs ADD COLUMN IF NOT EXISTS skipped_count integer NOT NULL DEFAULT 0;
ALTER TABLE backup_vault.backup_jobs ADD COLUMN IF NOT EXISTS retention_until timestamptz;
ALTER TABLE backup_vault.backup_jobs ADD COLUMN IF NOT EXISTS payload_target text NOT NULL DEFAULT 'NEON';
ALTER TABLE backup_vault.backup_jobs ADD COLUMN IF NOT EXISTS directory_count integer NOT NULL DEFAULT 0;
ALTER TABLE backup_vault.backup_jobs ADD COLUMN IF NOT EXISTS active_duration_seconds numeric(14,3) NOT NULL DEFAULT 0;
ALTER TABLE backup_vault.backup_jobs ADD COLUMN IF NOT EXISTS avg_speed_bps bigint NOT NULL DEFAULT 0;
ALTER TABLE backup_vault.backup_jobs ADD COLUMN IF NOT EXISTS peak_transfer_bps bigint NOT NULL DEFAULT 0;
ALTER TABLE backup_vault.backup_jobs ADD COLUMN IF NOT EXISTS compression_saved_bytes bigint NOT NULL DEFAULT 0;
ALTER TABLE backup_vault.backup_jobs ADD COLUMN IF NOT EXISTS chunk_count integer NOT NULL DEFAULT 0;
ALTER TABLE backup_vault.backup_jobs ADD COLUMN IF NOT EXISTS largest_file_bytes bigint NOT NULL DEFAULT 0;
ALTER TABLE backup_vault.backup_jobs ADD COLUMN IF NOT EXISTS scan_duration_seconds numeric(14,3) NOT NULL DEFAULT 0;
ALTER TABLE backup_vault.backup_jobs ADD COLUMN IF NOT EXISTS upload_stage_seconds numeric(14,3) NOT NULL DEFAULT 0;
ALTER TABLE backup_vault.backup_jobs ADD COLUMN IF NOT EXISTS processing_seconds numeric(14,3) NOT NULL DEFAULT 0;
ALTER TABLE backup_vault.backup_jobs ADD COLUMN IF NOT EXISTS b2_request_seconds numeric(14,3) NOT NULL DEFAULT 0;
ALTER TABLE backup_vault.backup_jobs ADD COLUMN IF NOT EXISTS metadata_seconds numeric(14,3) NOT NULL DEFAULT 0;
ALTER TABLE backup_vault.backup_jobs ADD COLUMN IF NOT EXISTS upload_worker_count integer NOT NULL DEFAULT 1;
ALTER TABLE backup_vault.backup_jobs ADD COLUMN IF NOT EXISTS recovery_state text NOT NULL DEFAULT 'NONE';
ALTER TABLE backup_vault.backup_jobs ADD COLUMN IF NOT EXISTS interrupted_at timestamptz;
ALTER TABLE backup_vault.backup_jobs ADD COLUMN IF NOT EXISTS resume_from_job_id uuid;
ALTER TABLE backup_vault.backup_jobs ADD COLUMN IF NOT EXISTS resumed_by_job_id uuid;
ALTER TABLE backup_vault.backup_jobs ADD COLUMN IF NOT EXISTS resumed_file_count integer NOT NULL DEFAULT 0;

ALTER TABLE backup_vault.backup_jobs DROP CONSTRAINT IF EXISTS backup_jobs_status_check;
ALTER TABLE backup_vault.backup_jobs ADD CONSTRAINT backup_jobs_status_check
  CHECK (status IN ('RUNNING','SUCCESS','PARTIAL','FAILED','CANCELLED','BLOCKED_LIMIT','INTERRUPTED'));

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='backup_jobs_recovery_state_check' AND conrelid='backup_vault.backup_jobs'::regclass) THEN
    ALTER TABLE backup_vault.backup_jobs ADD CONSTRAINT backup_jobs_recovery_state_check
      CHECK (recovery_state IN ('NONE','RECOVERABLE','RESUMED','DISCARDED'));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='backup_jobs_resumed_file_count_check' AND conrelid='backup_vault.backup_jobs'::regclass) THEN
    ALTER TABLE backup_vault.backup_jobs ADD CONSTRAINT backup_jobs_resumed_file_count_check CHECK (resumed_file_count >= 0);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='backup_jobs_resume_from_fk' AND conrelid='backup_vault.backup_jobs'::regclass) THEN
    ALTER TABLE backup_vault.backup_jobs ADD CONSTRAINT backup_jobs_resume_from_fk FOREIGN KEY (resume_from_job_id) REFERENCES backup_vault.backup_jobs(id) ON DELETE SET NULL;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='backup_jobs_resumed_by_fk' AND conrelid='backup_vault.backup_jobs'::regclass) THEN
    ALTER TABLE backup_vault.backup_jobs ADD CONSTRAINT backup_jobs_resumed_by_fk FOREIGN KEY (resumed_by_job_id) REFERENCES backup_vault.backup_jobs(id) ON DELETE SET NULL;
  END IF;
END $$;
CREATE INDEX IF NOT EXISTS idx_backup_jobs_recovery ON backup_vault.backup_jobs(status,recovery_state,started_at DESC);
CREATE INDEX IF NOT EXISTS idx_backup_jobs_resume_from ON backup_vault.backup_jobs(resume_from_job_id) WHERE resume_from_job_id IS NOT NULL;


DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='backup_jobs_backup_mode_check' AND conrelid='backup_vault.backup_jobs'::regclass) THEN
    ALTER TABLE backup_vault.backup_jobs
      ADD CONSTRAINT backup_jobs_backup_mode_check CHECK (backup_mode IN ('AUTO','FULL','INCREMENTAL','QUICK'));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='backup_jobs_payload_target_check' AND conrelid='backup_vault.backup_jobs'::regclass) THEN
    ALTER TABLE backup_vault.backup_jobs
      ADD CONSTRAINT backup_jobs_payload_target_check CHECK (payload_target IN ('NEON','B2'));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='backup_jobs_metrics_nonnegative_check' AND conrelid='backup_vault.backup_jobs'::regclass) THEN
    ALTER TABLE backup_vault.backup_jobs
      ADD CONSTRAINT backup_jobs_metrics_nonnegative_check CHECK (
        file_count>=0 AND original_bytes>=0 AND stored_bytes>=0 AND deduplicated_bytes>=0
        AND scanned_count>=0 AND changed_count>=0 AND skipped_count>=0
      );
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='backup_jobs_report_metrics_nonnegative_check' AND conrelid='backup_vault.backup_jobs'::regclass) THEN
    ALTER TABLE backup_vault.backup_jobs
      ADD CONSTRAINT backup_jobs_report_metrics_nonnegative_check CHECK (
        directory_count>=0 AND active_duration_seconds>=0 AND avg_speed_bps>=0 AND peak_transfer_bps>=0
        AND compression_saved_bytes>=0 AND chunk_count>=0 AND largest_file_bytes>=0
      );
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='backup_jobs_performance_metrics_nonnegative_check' AND conrelid='backup_vault.backup_jobs'::regclass) THEN
    ALTER TABLE backup_vault.backup_jobs
      ADD CONSTRAINT backup_jobs_performance_metrics_nonnegative_check CHECK (
        scan_duration_seconds>=0 AND upload_stage_seconds>=0 AND processing_seconds>=0
        AND b2_request_seconds>=0 AND metadata_seconds>=0 AND upload_worker_count BETWEEN 1 AND 8
      );
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS backup_vault.files (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id uuid NOT NULL REFERENCES backup_vault.backup_jobs(id) ON DELETE CASCADE,
  original_path text NOT NULL,
  file_name text NOT NULL,
  extension text,
  mime_type text,
  modified_at timestamptz,
  original_size bigint NOT NULL,
  stored_size bigint NOT NULL DEFAULT 0,
  sha256 text NOT NULL,
  content_sha256 text,
  compression text NOT NULL DEFAULT 'NONE',
  encryption text NOT NULL DEFAULT 'AES-256-GCM',
  chunk_count integer NOT NULL DEFAULT 0,
  status text NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','STORED','DEDUPED','FAILED','DELETED')),
  logical_path_hmac text,
  retention_until timestamptz,
  cleanup_eligible boolean NOT NULL DEFAULT false,
  payload_backend text NOT NULL DEFAULT 'NEON',
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_files_sha256 ON backup_vault.files(sha256);
CREATE INDEX IF NOT EXISTS idx_files_job ON backup_vault.files(job_id);
CREATE INDEX IF NOT EXISTS idx_files_created ON backup_vault.files(created_at DESC);
ALTER TABLE backup_vault.files ADD COLUMN IF NOT EXISTS logical_path_hmac text;
ALTER TABLE backup_vault.files ADD COLUMN IF NOT EXISTS retention_until timestamptz;
ALTER TABLE backup_vault.files ADD COLUMN IF NOT EXISTS cleanup_eligible boolean NOT NULL DEFAULT false;
ALTER TABLE backup_vault.files ADD COLUMN IF NOT EXISTS payload_backend text NOT NULL DEFAULT 'NEON';

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='files_sizes_nonnegative_check' AND conrelid='backup_vault.files'::regclass) THEN
    ALTER TABLE backup_vault.files
      ADD CONSTRAINT files_sizes_nonnegative_check CHECK (original_size>=0 AND stored_size>=0 AND chunk_count>=0);
  END IF;
END $$;
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='files_payload_backend_check' AND conrelid='backup_vault.files'::regclass) THEN
    ALTER TABLE backup_vault.files ADD CONSTRAINT files_payload_backend_check CHECK (payload_backend IN ('NEON','B2'));
  END IF;
END $$;
CREATE INDEX IF NOT EXISTS idx_files_logical_path ON backup_vault.files(logical_path_hmac, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_files_cleanup ON backup_vault.files(cleanup_eligible) WHERE cleanup_eligible=true;

CREATE TABLE IF NOT EXISTS backup_vault.file_chunks (
  file_id uuid NOT NULL REFERENCES backup_vault.files(id) ON DELETE CASCADE,
  chunk_no integer NOT NULL CHECK (chunk_no >= 0),
  nonce bytea NOT NULL,
  encrypted_data bytea,
  chunk_sha256 text NOT NULL,
  stored_bytes integer NOT NULL,
  storage_backend text NOT NULL DEFAULT 'NEON',
  object_key text,
  object_etag text,
  PRIMARY KEY (file_id, chunk_no)
);
ALTER TABLE backup_vault.file_chunks ALTER COLUMN encrypted_data DROP NOT NULL;
ALTER TABLE backup_vault.file_chunks ADD COLUMN IF NOT EXISTS storage_backend text NOT NULL DEFAULT 'NEON';
ALTER TABLE backup_vault.file_chunks ADD COLUMN IF NOT EXISTS object_key text;
ALTER TABLE backup_vault.file_chunks ADD COLUMN IF NOT EXISTS object_etag text;
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='file_chunks_storage_backend_check' AND conrelid='backup_vault.file_chunks'::regclass) THEN
    ALTER TABLE backup_vault.file_chunks ADD CONSTRAINT file_chunks_storage_backend_check CHECK (storage_backend IN ('NEON','B2'));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='file_chunks_payload_location_check' AND conrelid='backup_vault.file_chunks'::regclass) THEN
    ALTER TABLE backup_vault.file_chunks ADD CONSTRAINT file_chunks_payload_location_check CHECK (
      (storage_backend='NEON' AND encrypted_data IS NOT NULL) OR
      (storage_backend='B2' AND object_key IS NOT NULL)
    );
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS backup_vault.restore_tests (
  id bigserial PRIMARY KEY,
  job_id uuid REFERENCES backup_vault.backup_jobs(id) ON DELETE SET NULL,
  file_id uuid REFERENCES backup_vault.files(id) ON DELETE SET NULL,
  run_at timestamptz NOT NULL DEFAULT now(),
  result text NOT NULL CHECK (result IN ('PASS','WARN','FAIL')),
  hash_match boolean,
  restored_bytes bigint,
  details text
);


CREATE TABLE IF NOT EXISTS backup_vault.backup_verifications (
  id bigserial PRIMARY KEY,
  job_id uuid NOT NULL REFERENCES backup_vault.backup_jobs(id) ON DELETE CASCADE,
  mode text NOT NULL CHECK (mode IN ('QUICK','FULL')),
  started_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  result text NOT NULL CHECK (result IN ('PASS','WARN','FAIL','CANCELLED')),
  checked_files integer NOT NULL DEFAULT 0 CHECK (checked_files >= 0),
  checked_chunks integer NOT NULL DEFAULT 0 CHECK (checked_chunks >= 0),
  checked_bytes bigint NOT NULL DEFAULT 0 CHECK (checked_bytes >= 0),
  missing_objects integer NOT NULL DEFAULT 0 CHECK (missing_objects >= 0),
  hash_failures integer NOT NULL DEFAULT 0 CHECK (hash_failures >= 0),
  details text,
  app_version text
);
CREATE INDEX IF NOT EXISTS idx_backup_verifications_job ON backup_vault.backup_verifications(job_id, finished_at DESC);
CREATE INDEX IF NOT EXISTS idx_backup_verifications_result ON backup_vault.backup_verifications(result, finished_at DESC);

CREATE TABLE IF NOT EXISTS backup_vault.usage_snapshots (
  id bigserial PRIMARY KEY,
  captured_at timestamptz NOT NULL DEFAULT now(),
  target_id uuid REFERENCES backup_vault.storage_targets(id),
  database_bytes bigint NOT NULL DEFAULT 0,
  file_payload_bytes bigint NOT NULL DEFAULT 0,
  percent_of_hard_limit numeric(7,2),
  status text NOT NULL DEFAULT 'OK' CHECK (status IN ('OK','WARN','BLOCK'))
);

CREATE TABLE IF NOT EXISTS backup_vault.tuev_checks (
  id bigserial PRIMARY KEY,
  run_at timestamptz NOT NULL DEFAULT now(),
  check_code text NOT NULL,
  check_name text NOT NULL,
  result text NOT NULL CHECK (result IN ('PASS','WARN','FAIL')),
  details text,
  app_version text,
  schema_version text
);
CREATE INDEX IF NOT EXISTS idx_tuev_run_at ON backup_vault.tuev_checks(run_at DESC);

CREATE OR REPLACE FUNCTION backup_vault.prevent_retention_delete()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  IF OLD.retention_until IS NOT NULL AND OLD.retention_until > now() THEN
    RAISE EXCEPTION 'Backup object is protected until %', OLD.retention_until;
  END IF;
  RETURN OLD;
END;
$$;

DROP TRIGGER IF EXISTS trg_protect_backup_jobs ON backup_vault.backup_jobs;
CREATE TRIGGER trg_protect_backup_jobs
BEFORE DELETE ON backup_vault.backup_jobs
FOR EACH ROW EXECUTE FUNCTION backup_vault.prevent_retention_delete();

DROP TRIGGER IF EXISTS trg_protect_files ON backup_vault.files;
CREATE TRIGGER trg_protect_files
BEFORE DELETE ON backup_vault.files
FOR EACH ROW EXECUTE FUNCTION backup_vault.prevent_retention_delete();

CREATE TABLE IF NOT EXISTS backup_vault.architecture_rules (
  id bigserial PRIMARY KEY,
  rule_code text NOT NULL UNIQUE,
  category text NOT NULL,
  rule_text text NOT NULL,
  severity text NOT NULL DEFAULT 'MANDATORY' CHECK (severity IN ('MANDATORY','RECOMMENDED','INFO')),
  active boolean NOT NULL DEFAULT true,
  version text NOT NULL DEFAULT '1.1',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO backup_vault.architecture_rules (rule_code, category, rule_text, severity, version) VALUES
('ISO-001','Isolation','Backup project must contain no KC mirroring, POS, roster or Futura tables, triggers or replication.','MANDATORY','1.0'),
('SEC-001','Credentials','Database passwords and connection strings are never stored inside the backup database. They stay only in the local operating-system credential store.','MANDATORY','1.0'),
('SEC-002','Encryption','File contents are encrypted on the PC before upload with AES-256-GCM.','MANDATORY','1.0'),
('CAP-001','Capacity','Run a capacity check before each backup. Warn at the soft limit and block uploads at the hard limit.','MANDATORY','1.0'),
('INT-001','Integrity','Verify every file and every chunk with SHA-256. A restore counts as successful only after hash verification.','MANDATORY','1.0'),
('OPS-001','Restore','A backup is valid only if restore testing succeeds.','MANDATORY','1.0'),
('CMP-001','Compression','Do not recompress already compressed formats by default. Compress other files only when it reduces size.','RECOMMENDED','1.0'),
('OPS-002','Scheduler','Windows Scheduler tasks must never contain database passwords, DSNs or encryption keys. Scheduled jobs may only start the local runner.','MANDATORY','1.1'),
('OPS-003','Scheduler','Every one-touch or scheduled backup must run the same capacity, encryption, deduplication and Christmas-market guard checks as a manual backup.','MANDATORY','1.1'),
('RST-002','Restore','Explorer restore must allow single-file and whole-folder recovery while preserving the original directory structure and without silent overwrite.','MANDATORY','1.1'),
('UX-001','Privacy','Encrypted file names and paths may be decrypted only locally in the backup application for Explorer display.','MANDATORY','1.1'),
('MON-001','Monitoring','The dashboard must show backup status, capacity, files, directories, speed, restore tests and health checks in a user-friendly overview.','RECOMMENDED','1.2'),
('MON-002','Monitoring','Dashboard statistics may read encrypted metadata from Neon, but all decryption of names and paths must happen only on the local PC.','MANDATORY','1.2'),
('OPS-004','Backup modes','The user can explicitly select Full, Incremental or Quick backup, or let the application recommend a mode.','MANDATORY','1.3'),
('OPS-005','Backup modes','Quick mode may use size and modification time to skip unchanged files; Full and Incremental modes must use content hashes for change detection.','MANDATORY','1.3'),
('IMM-001','Immutability','Backup jobs and file versions are protected against deletion until their local retention period has expired.','MANDATORY','1.3'),
('VER-001','Versioning','Version retention is tracked by a deterministic local HMAC of the logical file path without exposing the real path in Neon.','MANDATORY','1.3'),
('RST-003','Restore','After successful backups the application may perform a small automatic restore self-test with strict size limits.','RECOMMENDED','1.3'),
('COPY-001','Redundancy','A One-Touch plan may optionally write a second independent copy to a separately configured database target; this is disabled by default.','RECOMMENDED','1.3'),
('UX-002','Usability','Required input fields must be clearly marked with a red asterisk and saving must be blocked when mandatory input is missing or invalid.','MANDATORY','1.4'),
('UX-003','Usability','End-user scheduler choices and weekdays must be displayed in German while stable internal codes remain unchanged.','RECOMMENDED','1.4'),
('VAL-001','Validation','Database constraints reject unknown backup modes and negative backup/file metrics even if data is written outside the normal application.','MANDATORY','1.4.1'),
('UX-004','Usability','Primary actions, navigation and settings must be visually grouped and consistently ordered.','RECOMMENDED','1.4'),
('MON-004','Monitoring','Live backup status must show percent, file count, processed data, processing speed, elapsed time and estimated remaining time using low-overhead local UI updates.','RECOMMENDED','1.4.5'),
('UX-005','Performance','The live round progress indicator must use lightweight native Tk drawing and be throttled so monitoring does not materially slow backup work.','MANDATORY','1.4.5'),
('OBJ-001','Storage','Neon stores Core, catalog, hashes, history and audit metadata; large encrypted file payloads may be stored in S3-compatible object storage such as Backblaze B2.','MANDATORY','1.5'),
('OBJ-002','Storage','Backblaze B2 credentials must be stored only in the local operating-system credential store and never in Neon or config.json.','MANDATORY','1.5'),
('OBJ-003','Storage','Every object-storage chunk is encrypted locally with AES-256-GCM and verified by SHA-256 after download before restore.','MANDATORY','1.5'),
('OBJ-004','Storage','The user may choose Automatic, Backblaze B2 or Neon-small-backup payload storage; Automatic prefers B2 when configured.','RECOMMENDED','1.5'),
('OPS-006','Runtime control','Manual and One-Touch backup runs must support cooperative Pause/Resume and safe user cancellation without corrupting a valid backup state.','MANDATORY','1.5.3'),
('OPS-007','Cancellation','Cancelling an in-progress backup must mark the job CANCELLED and roll back incomplete payload metadata; B2 objects created only by that cancelled run must be removed when possible.','MANDATORY','1.5.3'),
('SEC-010','Emergency recovery','Emergency recovery bundles must be encrypted locally with a password-derived key and must never store the emergency password.','MANDATORY','1.6.0'),
('SEC-011','Backup pass QR','The phone/print Backup Pass and its QR code must contain no database passwords, B2 application keys, DSNs or plaintext recovery keys.','MANDATORY','1.6.0'),
('OPS-008','Disaster recovery','Importing an encrypted recovery bundle may restore credentials only into the local OS credential store and local configuration after explicit user confirmation.','MANDATORY','1.5.4'),
('VER-010','Verification','Every successful backup may be followed by a low-overhead quick verification of repository metadata and object presence; the user can trigger a full content verification that downloads, decrypts and checks SHA-256.','MANDATORY','1.6'),
('VER-011','Verification audit','Verification runs must be stored separately with mode, result, checked files/chunks/bytes, missing objects and hash failures.','MANDATORY','1.6'),
('RPT-001','Reporting','Every completed backup job must expose a report with file and directory counts, data volume, duration, average speed, storage split, deduplication, compression and verification status.','MANDATORY','1.6'),
('UX-010','Usability','Large file, explorer, history and audit lists must provide visible vertical and horizontal scrollbars where content can exceed the viewport.','RECOMMENDED','1.6'),
('UX-011','Usability','Dashboard charts use consistent semantic colors, readable labels and professional bar, column, line and donut visualizations.','RECOMMENDED','1.6.1'),
('UX-012','Usability','Dashboard and history must support day, week, month, quarter, year and custom date filters plus status, backup mode, storage, verification and text search.','MANDATORY','1.6.1'),
('PERF-001','Performance','Backblaze B2 clients must be reused within a run; backup code must not create a new S3 client for every chunk or object request.','MANDATORY','1.6.2'),
('PERF-002','Performance','Large B2 backup runs may use bounded parallel file uploads. Worker count is capped, cancellation remains cooperative and all payloads stay locally encrypted before upload.','MANDATORY','1.6.2'),
('PERF-003','Performance','Backup jobs record scan, upload stage, processing, B2 request and metadata timing so bottlenecks can be distinguished from total runtime.','MANDATORY','1.6.2'),
('UX-013','Usability','Dashboard charts must keep readable minimum dimensions and use scrolling/responsive layout instead of clipping titles, axes, values or legends.','MANDATORY','1.6.3'),
('MON-020','Monitoring','The main window must expose a persistent system status bar for Neon, object storage, local vault, scheduler, verification/TÜV and KC Communication; online services also expose recent data activity.','RECOMMENDED','1.6.3'),
('COM-001','Communication','KC Communication integration may transmit event metadata only. Backup payloads, original file paths, recovery keys, database DSNs and B2 credentials must never be sent.','MANDATORY','1.6.3'),
('SEC-020','Communication security','KC Communication authentication tokens must remain only in the local OS credential store and never in Neon, config.json or backup reports.','MANDATORY','1.6.3'),
('LOG-001','Diagnostics','Start protocol logging is user-configurable, contains no credentials or recovery secrets and can be disabled for normal production operation.','MANDATORY','1.6.3'),
('REC-001','Crash recovery','Unexpected process or power loss must leave an encrypted local checkpoint so the next start can offer a safe continuation.','MANDATORY','1.7.0'),
('REC-002','Crash recovery','Recovery checkpoints must never persist original file paths in plaintext and must use authenticated AES-256-GCM encryption.','MANDATORY','1.7.0'),
('REC-003','Crash recovery','Manual CANCELLED and known FAILED runs are not automatically treated as recoverable interruptions.','MANDATORY','1.7.0'),
('REC-004','Crash recovery','A resumed run must link to the interrupted job and may reuse only complete unchanged STORED/DEDUPED file versions.','MANDATORY','1.7.0'),
('OPS-010','Runtime control','Only one local PC Backup Vault process may own the backup runtime at a time; UI and scheduler must share the same process lock.','MANDATORY','1.7.0'),
('COM-010','KC Communication','PC Backup Vault must use the central kc-communication-machine contract with device pairing rather than an arbitrary webhook.','MANDATORY','1.7.0'),
('COM-011','KC Communication','The KC machine device token is generated locally and stored only in the OS credential store; the pairing code is non-secret.','MANDATORY','1.7.0'),
('PERF-010','Dashboard','Dashboard opening must not synchronously load/decrypt the complete file catalog; inventory data is loaded lazily only when required.','MANDATORY','1.7.0')
ON CONFLICT (rule_code) DO UPDATE SET rule_text=EXCLUDED.rule_text,severity=EXCLUDED.severity,version=EXCLUDED.version,updated_at=now();
