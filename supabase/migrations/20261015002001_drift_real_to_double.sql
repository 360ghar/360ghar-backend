-- Schema drift: REAL columns the ORM declares DOUBLE PRECISION.
--
-- Contract rule: coordinates and measures are DOUBLE PRECISION. REAL keeps about 7 digits.
--   agents.user_satisfaction_rating
--   user_search_history.user_location_lat, user_location_lng
--
-- The cast goes through text. PostgreSQL prints a REAL as the shortest decimal that round-trips
-- (extra_float_digits = 1), so 28.613939 stays 28.613939 and 4.3 stays 4.3. A direct REAL to
-- DOUBLE cast keeps the binary noise (28.6139392852783, 4.300000190734863). A cast through
-- NUMERIC keeps only 6 digits, which moves a coordinate by metres.
-- Not applied to any database. The integrator applies it after owner approval.

SET LOCAL extra_float_digits = 1;

ALTER TABLE public.agents
    ALTER COLUMN user_satisfaction_rating TYPE DOUBLE PRECISION
    USING user_satisfaction_rating::text::double precision;

ALTER TABLE public.user_search_history
    ALTER COLUMN user_location_lat TYPE DOUBLE PRECISION
    USING user_location_lat::text::double precision,
    ALTER COLUMN user_location_lng TYPE DOUBLE PRECISION
    USING user_location_lng::text::double precision;
