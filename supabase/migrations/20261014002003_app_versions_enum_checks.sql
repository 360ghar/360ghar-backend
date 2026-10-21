-- ============================================================
-- App versions: enum columns as CHECK constraints.
-- ============================================================
-- app_versions.app and app_versions.platform were plain VARCHAR, so a retired
-- slug (ghar360) was accepted again. The values now match AppKey
-- (ghar, estate, flatmates, stays) and DevicePlatform (ios, android, web).
--
-- 20261014002000 maps ghar360 to ghar and lowercases platform before this runs.
-- A row with any other value makes this migration fail. The transaction then
-- rolls back. Fix that row, then run again.
--
-- Not applied by this change. Run with scripts/run_supabase_migrations.py.
-- ============================================================

ALTER TABLE app_versions
    ADD CONSTRAINT app_versions_app_check
    CHECK (app IN ('ghar', 'estate', 'flatmates', 'stays'));

ALTER TABLE app_versions
    ADD CONSTRAINT app_versions_platform_check
    CHECK (platform IN ('ios', 'android', 'web'));
