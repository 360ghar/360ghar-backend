-- ============================================================
-- Normalize legacy furnishing_level values to the canonical contract
-- ============================================================
-- The properties.furnishing_level column is free-form VARCHAR(32) and holds
-- legacy display-grade values (fully-furnished, Fully Furnished,
-- semi-furnished, ...) which fail the strict Literal response validation in
-- app/schemas/property.py and 422 the whole GET /properties page.
-- This migration rewrites known variants to the canonical
-- furnished / semi_furnished / unfurnished values; anything else becomes
-- NULL so a single dirty row can never break search again.
-- Idempotent: the WHERE clause only matches non-canonical values.
-- No CHECK constraint here (deferred to a follow-up) so deploy never
-- blocks on dirty rows.
-- ============================================================

UPDATE properties
SET furnishing_level = CASE
    WHEN lower(trim(furnishing_level)) IN (
        'furnished', 'fully-furnished', 'fully furnished', 'fully_furnished',
        'fullyfurnished', 'full-furnished', 'full furnished', 'full_furnished'
    ) THEN 'furnished'
    WHEN lower(trim(furnishing_level)) IN (
        'semi_furnished', 'semi-furnished', 'semi furnished', 'semifurnished',
        'partially-furnished', 'partially furnished', 'partially_furnished',
        'partly-furnished', 'partly furnished', 'partly_furnished'
    ) THEN 'semi_furnished'
    WHEN lower(trim(furnishing_level)) IN ('unfurnished', 'none') THEN 'unfurnished'
    ELSE NULL
END
WHERE furnishing_level IS NOT NULL
  AND furnishing_level NOT IN ('furnished', 'semi_furnished', 'unfurnished');

-- Verification (run manually): expect zero rows.
-- SELECT DISTINCT furnishing_level FROM properties
-- WHERE furnishing_level NOT IN ('furnished', 'semi_furnished', 'unfurnished');
