-- furnishing_level stores only the canonical FurnishingLevel values. The normalization
-- migration (20260925000001) rewrote the legacy variants. Any value still outside the set
-- becomes NULL, then a CHECK constraint keeps the column to the canonical values.
-- Idempotent: the UPDATE matches only non-canonical values, and the constraint is added once.

UPDATE properties
SET furnishing_level = NULL
WHERE furnishing_level IS NOT NULL
  AND furnishing_level NOT IN ('furnished', 'semi_furnished', 'unfurnished');

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'properties_furnishing_level_check'
          AND conrelid = 'public.properties'::regclass
    ) THEN
        ALTER TABLE properties
            ADD CONSTRAINT properties_furnishing_level_check
            CHECK (furnishing_level IS NULL
                   OR furnishing_level IN ('furnished', 'semi_furnished', 'unfurnished'));
    END IF;
END $$;
