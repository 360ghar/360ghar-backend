-- ============================================================
-- Users and core contract: data cleanup and NOT NULL constraints.
-- ============================================================
-- 1. app_versions.app: the retired key 'ghar360' becomes 'ghar' (AppKey).
-- 2. app_versions.platform: lowercase (the wire value is lowercase).
-- 3. faqs.display_order: NULL becomes 0, then NOT NULL with default 0.
-- 4. bug_reports.status: NULL becomes 'open', then NOT NULL.
-- 5. users.notification_settings: drop the keys that are not in the contract:
--    "categories" (it re-enabled marketing), "quietHours", "quiet_hours" and
--    "frequency". Values are dropped, not renamed (decisions.md, BE-notify).
-- 6. users.current_latitude / current_longitude: DOUBLE PRECISION (was REAL).
--    Coordinates are DOUBLE PRECISION on the wire contract.
--
-- Re-run safe: every UPDATE filters on the old value, and SET NOT NULL
-- on a column that is already NOT NULL is a no-op.
-- Not applied by this change. Run with scripts/run_supabase_migrations.py.
-- ============================================================

UPDATE app_versions SET app = 'ghar' WHERE app = 'ghar360';

UPDATE app_versions SET platform = lower(platform) WHERE platform <> lower(platform);

UPDATE faqs SET display_order = 0 WHERE display_order IS NULL;

ALTER TABLE faqs ALTER COLUMN display_order SET DEFAULT 0;

ALTER TABLE faqs ALTER COLUMN display_order SET NOT NULL;

UPDATE bug_reports SET status = 'open' WHERE status IS NULL;

ALTER TABLE bug_reports ALTER COLUMN status SET NOT NULL;

UPDATE users
SET notification_settings = notification_settings
    - 'categories' - 'quietHours' - 'quiet_hours' - 'frequency'
WHERE notification_settings ?| array['categories', 'quietHours', 'quiet_hours', 'frequency'];

ALTER TABLE users
    ALTER COLUMN current_latitude TYPE DOUBLE PRECISION,
    ALTER COLUMN current_longitude TYPE DOUBLE PRECISION;
