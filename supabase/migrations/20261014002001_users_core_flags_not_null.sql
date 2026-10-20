-- ============================================================
-- Users and core: NOT NULL on flags and created_at.
-- ============================================================
-- The ORM declares these columns non-null (Mapped[bool], Mapped[int],
-- Mapped[datetime]). The DDL allowed NULL. Backfill the NULL rows with the
-- column default, then set NOT NULL.
--
-- Re-run safe: every UPDATE filters on IS NULL, and SET NOT NULL on a column
-- that is already NOT NULL is a no-op.
-- Not applied by this change. Run with scripts/run_supabase_migrations.py.
-- ============================================================

UPDATE users SET is_active = TRUE WHERE is_active IS NULL;
ALTER TABLE users ALTER COLUMN is_active SET NOT NULL;

UPDATE users SET is_verified = FALSE WHERE is_verified IS NULL;
ALTER TABLE users ALTER COLUMN is_verified SET NOT NULL;

UPDATE users SET created_at = now() WHERE created_at IS NULL;
ALTER TABLE users ALTER COLUMN created_at SET NOT NULL;

UPDATE faqs SET is_active = TRUE WHERE is_active IS NULL;
ALTER TABLE faqs ALTER COLUMN is_active SET NOT NULL;

UPDATE faqs SET created_at = now() WHERE created_at IS NULL;
ALTER TABLE faqs ALTER COLUMN created_at SET NOT NULL;

UPDATE pages SET format = 'html' WHERE format IS NULL;
ALTER TABLE pages ALTER COLUMN format SET NOT NULL;

UPDATE pages SET is_active = TRUE WHERE is_active IS NULL;
ALTER TABLE pages ALTER COLUMN is_active SET NOT NULL;

UPDATE pages SET is_draft = FALSE WHERE is_draft IS NULL;
ALTER TABLE pages ALTER COLUMN is_draft SET NOT NULL;

UPDATE pages SET view_count = 0 WHERE view_count IS NULL;
ALTER TABLE pages ALTER COLUMN view_count SET NOT NULL;

UPDATE pages SET created_at = now() WHERE created_at IS NULL;
ALTER TABLE pages ALTER COLUMN created_at SET NOT NULL;

UPDATE bug_reports SET created_at = now() WHERE created_at IS NULL;
ALTER TABLE bug_reports ALTER COLUMN created_at SET NOT NULL;

UPDATE app_versions SET is_mandatory = FALSE WHERE is_mandatory IS NULL;
ALTER TABLE app_versions ALTER COLUMN is_mandatory SET NOT NULL;

UPDATE app_versions SET is_active = TRUE WHERE is_active IS NULL;
ALTER TABLE app_versions ALTER COLUMN is_active SET NOT NULL;

UPDATE app_versions SET created_at = now() WHERE created_at IS NULL;
ALTER TABLE app_versions ALTER COLUMN created_at SET NOT NULL;
