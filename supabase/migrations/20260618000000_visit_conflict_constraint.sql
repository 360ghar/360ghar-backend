-- Visit conflict detection: prevent overlapping active visits for the same user.
--
-- The visits table has no explicit duration column, so each visit is treated as
-- occupying a fixed 60-minute window starting at scheduled_date (matching the
-- application default VISIT_DEFAULT_DURATION_MINUTES). Cancelled and completed
-- visits are excluded from the constraint so they never block new bookings.
--
-- This DB-level EXCLUDE constraint guards against race conditions where two
-- concurrent requests both pass the application-level overlap check.

-- btree_gist allows combining GiST range exclusion with scalar (user_id) columns.
CREATE EXTENSION IF NOT EXISTS btree_gist;

ALTER TABLE public.visits
  DROP CONSTRAINT IF EXISTS visits_no_overlap_per_user;

ALTER TABLE public.visits
  ADD CONSTRAINT visits_no_overlap_per_user
  EXCLUDE USING gist (
    user_id WITH =,
    tstzrange(
      scheduled_date,
      scheduled_date + interval '60 minutes'
    ) WITH &&
  )
  WHERE (status NOT IN ('cancelled', 'completed'));
