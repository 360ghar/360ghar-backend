-- Schema drift: NOT NULL on columns the ORM declares NOT NULL.
--
-- Every column below has a DEFAULT in the database and a default in the ORM, so the app
-- never writes NULL. The tables were created with the column nullable. Each NULL row (none
-- is expected) is backfilled, then the column is set NOT NULL.
--
-- Backfill values:
--   created_at, updated_at: now(). The original time was not stored. custom_domains.updated_at
--     takes created_at, which is set first.
--   Counters (agents.total_users_assigned, ai_jobs.progress, ai_jobs.retry_count, tours.*_count):
--     0, the column default.
--   agents.user_satisfaction_rating: 0, the column default.
--   Flags that expose a row (agents.is_active, agents.is_available, hotspots.is_active,
--     tours.is_public, tours.is_featured): FALSE. A NULL flag already reads as false in every
--     query (WHERE is_active), so FALSE keeps today's behaviour. A migration must not activate
--     an agent or publish a tour.
--   media_files.visibility: 'private', the column default and the safe value.
--   Other flags (bookings.early_check_in, bookings.late_check_out, visits.follow_up_required,
--     media_files.is_processed, scenes.is_processed): FALSE, the column default.
--   floor_plans.floor_number: 1, the column default.
--   visits.status: 'requested', the column default.
-- Not applied to any database. The integrator applies it after owner approval.

-- agents
UPDATE public.agents SET created_at = now() WHERE created_at IS NULL;
UPDATE public.agents SET is_active = FALSE WHERE is_active IS NULL;
UPDATE public.agents SET is_available = FALSE WHERE is_available IS NULL;
UPDATE public.agents SET total_users_assigned = 0 WHERE total_users_assigned IS NULL;
UPDATE public.agents SET user_satisfaction_rating = 0 WHERE user_satisfaction_rating IS NULL;
ALTER TABLE public.agents
    ALTER COLUMN created_at SET NOT NULL,
    ALTER COLUMN is_active SET NOT NULL,
    ALTER COLUMN is_available SET NOT NULL,
    ALTER COLUMN total_users_assigned SET NOT NULL,
    ALTER COLUMN user_satisfaction_rating SET NOT NULL;

-- agent_interactions
UPDATE public.agent_interactions SET created_at = now() WHERE created_at IS NULL;
ALTER TABLE public.agent_interactions ALTER COLUMN created_at SET NOT NULL;

-- ai_jobs
UPDATE public.ai_jobs SET progress = 0 WHERE progress IS NULL;
UPDATE public.ai_jobs SET retry_count = 0 WHERE retry_count IS NULL;
ALTER TABLE public.ai_jobs
    ALTER COLUMN progress SET NOT NULL,
    ALTER COLUMN retry_count SET NOT NULL;

-- bookings
UPDATE public.bookings SET created_at = now() WHERE created_at IS NULL;
UPDATE public.bookings SET early_check_in = FALSE WHERE early_check_in IS NULL;
UPDATE public.bookings SET late_check_out = FALSE WHERE late_check_out IS NULL;
ALTER TABLE public.bookings
    ALTER COLUMN created_at SET NOT NULL,
    ALTER COLUMN early_check_in SET NOT NULL,
    ALTER COLUMN late_check_out SET NOT NULL;

-- custom_domains
UPDATE public.custom_domains SET created_at = now() WHERE created_at IS NULL;
UPDATE public.custom_domains SET updated_at = created_at WHERE updated_at IS NULL;
ALTER TABLE public.custom_domains
    ALTER COLUMN created_at SET NOT NULL,
    ALTER COLUMN updated_at SET NOT NULL;

-- floor_plans
UPDATE public.floor_plans SET floor_number = 1 WHERE floor_number IS NULL;
ALTER TABLE public.floor_plans ALTER COLUMN floor_number SET NOT NULL;

-- hotspots
UPDATE public.hotspots SET is_active = FALSE WHERE is_active IS NULL;
ALTER TABLE public.hotspots ALTER COLUMN is_active SET NOT NULL;

-- media_files
UPDATE public.media_files SET is_processed = FALSE WHERE is_processed IS NULL;
UPDATE public.media_files SET visibility = 'private' WHERE visibility IS NULL;
ALTER TABLE public.media_files
    ALTER COLUMN is_processed SET NOT NULL,
    ALTER COLUMN visibility SET NOT NULL;

-- scenes
UPDATE public.scenes SET is_processed = FALSE WHERE is_processed IS NULL;
ALTER TABLE public.scenes ALTER COLUMN is_processed SET NOT NULL;

-- tours
UPDATE public.tours SET is_featured = FALSE WHERE is_featured IS NULL;
UPDATE public.tours SET is_public = FALSE WHERE is_public IS NULL;
UPDATE public.tours SET like_count = 0 WHERE like_count IS NULL;
UPDATE public.tours SET share_count = 0 WHERE share_count IS NULL;
UPDATE public.tours SET view_count = 0 WHERE view_count IS NULL;
ALTER TABLE public.tours
    ALTER COLUMN is_featured SET NOT NULL,
    ALTER COLUMN is_public SET NOT NULL,
    ALTER COLUMN like_count SET NOT NULL,
    ALTER COLUMN share_count SET NOT NULL,
    ALTER COLUMN view_count SET NOT NULL;

-- user_search_history
UPDATE public.user_search_history SET created_at = now() WHERE created_at IS NULL;
ALTER TABLE public.user_search_history ALTER COLUMN created_at SET NOT NULL;

-- user_swipes
UPDATE public.user_swipes SET created_at = now() WHERE created_at IS NULL;
ALTER TABLE public.user_swipes ALTER COLUMN created_at SET NOT NULL;

-- visits
UPDATE public.visits SET created_at = now() WHERE created_at IS NULL;
UPDATE public.visits SET follow_up_required = FALSE WHERE follow_up_required IS NULL;
UPDATE public.visits SET status = 'requested' WHERE status IS NULL;
ALTER TABLE public.visits
    ALTER COLUMN created_at SET NOT NULL,
    ALTER COLUMN follow_up_required SET NOT NULL,
    ALTER COLUMN status SET NOT NULL;
