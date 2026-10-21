-- =============================================================================
-- Migration: 20260913000001_drop_splat_jobs_quarantine.sql
--
-- Drops the 3D Splat Lab `splat_jobs` table created by
-- 20260715000001_splat_jobs.sql (Gaussian Splatting pipeline jobs).
--
-- Splat removal was approved on 2026-10-14 (contract-audit/decisions.md), so this
-- runs with the normal migration runner. The splat code was removed in the same
-- integration branch.
-- =============================================================================

-- The updated_at trigger drops automatically with the table. A separate DROP TRIGGER
-- would fail when splat_jobs is absent.
-- RLS policies on splat_jobs (splat_jobs_select_own / insert_own / update_own /
-- delete_own) drop automatically with the table. Indexes
-- (idx_splat_jobs_user_id / idx_splat_jobs_status / idx_splat_jobs_user_created)
-- drop automatically with the table.
DROP TABLE IF EXISTS splat_jobs;

-- NOTE: update_updated_at_column() shared helper is intentionally KEPT – it is
-- created/used by other migrations (core, tours, blog, social, data_hub, etc.).
