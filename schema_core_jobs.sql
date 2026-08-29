CREATE SCHEMA IF NOT EXISTS backup_vault;

-- Generic control-plane job history. This table stores metadata/KPIs only.
-- Backup payload data remains exclusively in the existing backup tables/object storage.
CREATE TABLE IF NOT EXISTS backup_vault.core_jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  program_name text NOT NULL DEFAULT 'PC Backup Vault',
  job_type text NOT NULL,
  source text NOT NULL DEFAULT 'LOCAL',
  source_job_id text,
  started_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  status text NOT NULL,
  item_count bigint NOT NULL DEFAULT 0 CHECK (item_count >= 0),
  byte_count bigint NOT NULL DEFAULT 0 CHECK (byte_count >= 0),
  warning_count integer NOT NULL DEFAULT 0 CHECK (warning_count >= 0),
  error_count integer NOT NULL DEFAULT 0 CHECK (error_count >= 0),
  duration_seconds numeric(14,3) NOT NULL DEFAULT 0 CHECK (duration_seconds >= 0),
  summary text,
  metrics jsonb NOT NULL DEFAULT '{}'::jsonb,
  app_version text,
  device_id text,
  created_at timestamptz NOT NULL DEFAULT now()
);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname='core_jobs_job_type_check'
      AND conrelid='backup_vault.core_jobs'::regclass
  ) THEN
    ALTER TABLE backup_vault.core_jobs ADD CONSTRAINT core_jobs_job_type_check
      CHECK (job_type IN (
        'BACKUP','INVENTORY','GITHUB_COMPARE','GIT_HANDOFF','GIT_RECOVERY',
        'UPDATE_CHECK','UPDATE_INSTALL','VERIFY','RESTORE_TEST','TUEV','OTHER'
      ));
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname='core_jobs_status_check'
      AND conrelid='backup_vault.core_jobs'::regclass
  ) THEN
    ALTER TABLE backup_vault.core_jobs ADD CONSTRAINT core_jobs_status_check
      CHECK (status IN ('RUNNING','SUCCESS','PARTIAL','WARNING','FAILED','CANCELLED','BLOCKED','INTERRUPTED'));
  END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_core_jobs_source_identity
  ON backup_vault.core_jobs(source, source_job_id)
  WHERE source_job_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_core_jobs_started ON backup_vault.core_jobs(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_core_jobs_type_status ON backup_vault.core_jobs(job_type, status, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_core_jobs_program ON backup_vault.core_jobs(program_name, started_at DESC);

-- One read-only management surface over old backup jobs and new control-plane jobs.
CREATE OR REPLACE VIEW backup_vault.unified_jobs AS
SELECT
  ('backup:' || b.id::text) AS unified_id,
  'PC Backup Vault'::text AS program_name,
  'BACKUP'::text AS job_type,
  'BACKUP_JOBS'::text AS source,
  b.id::text AS source_job_id,
  b.started_at,
  b.finished_at,
  b.status,
  b.file_count::bigint AS item_count,
  b.original_bytes::bigint AS byte_count,
  CASE WHEN b.status IN ('PARTIAL','INTERRUPTED','BLOCKED_LIMIT') THEN 1 ELSE 0 END::integer AS warning_count,
  CASE WHEN b.status='FAILED' THEN 1 ELSE 0 END::integer AS error_count,
  COALESCE(b.active_duration_seconds, 0)::numeric(14,3) AS duration_seconds,
  COALESCE(b.note, '')::text AS summary,
  jsonb_build_object(
    'backup_mode', COALESCE(b.backup_mode, 'AUTO'),
    'payload_target', COALESCE(b.payload_target, 'NEON'),
    'stored_bytes', COALESCE(b.stored_bytes, 0),
    'deduplicated_bytes', COALESCE(b.deduplicated_bytes, 0),
    'changed_count', COALESCE(b.changed_count, 0),
    'skipped_count', COALESCE(b.skipped_count, 0)
  ) AS metrics,
  b.app_version,
  NULL::text AS device_id,
  b.started_at AS created_at
FROM backup_vault.backup_jobs b
UNION ALL
SELECT
  ('core:' || c.id::text) AS unified_id,
  c.program_name,
  c.job_type,
  c.source,
  c.source_job_id,
  c.started_at,
  c.finished_at,
  c.status,
  c.item_count,
  c.byte_count,
  c.warning_count,
  c.error_count,
  c.duration_seconds,
  COALESCE(c.summary, '')::text AS summary,
  c.metrics,
  c.app_version,
  c.device_id,
  c.created_at
FROM backup_vault.core_jobs c;

UPDATE backup_vault.core
SET schema_version='1.8.0', app_min_version='1.8.0', updated_at=now()
WHERE id=1;
