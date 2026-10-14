-- =============================================================================
-- QUARANTINE – UNAPPLIED – DEV ONLY – DO NOT APPLY TO PROD
-- Migration: 20260913000001_drop_splat_jobs_quarantine.sql
--
-- Drops the 3D Splat Lab `splat_jobs` table created by
-- 20260715000001_splat_jobs.sql (Gaussian Splatting pipeline jobs).
--
-- Status: UNAPPLIED by design. No DB writes have been performed in this pass.
-- Prod drop needs separate approval per spec
-- 2026-09-13-splat-removal-daytona-tour-keep.md.
-- Apply only against a dev/staging Supabase project, never prod, via:
--   uv run python scripts/run_supabase_migrations.py --file 20260913000001_drop_splat_jobs_quarantine.sql
-- =============================================================================

-- Drop the auto-updated trigger first (table-dependent).
DROP TRIGGER IF EXISTS set_splat_jobs_updated_at ON splat_jobs;

-- RLS policies on splat_jobs (splat_jobs_select_own / insert_own / update_own /
-- delete_own) drop automatically with the table. Indexes
-- (idx_splat_jobs_user_id / idx_splat_jobs_status / idx_splat_jobs_user_created)
-- drop automatically with the table.
DROP TABLE IF EXISTS splat_jobs;

-- NOTE: update_updated_at_column() shared helper is intentionally KEPT – it is
-- created/used by other migrations (core, tours, blog, social, data_hub, etc.).
