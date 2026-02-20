-- Add visibility enum and column to tours table
-- This replaces the boolean is_public with a more flexible visibility system

-- Create the visibility enum type
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'tour_visibility') THEN
        CREATE TYPE tour_visibility AS ENUM ('private', 'unlisted', 'public');
    END IF;
END$$;

-- Add visibility column with default value
ALTER TABLE tours
ADD COLUMN IF NOT EXISTS visibility tour_visibility NOT NULL DEFAULT 'private';

-- Migrate existing data: convert is_public boolean to visibility enum
UPDATE tours
SET visibility = CASE
    WHEN is_public = true THEN 'public'::tour_visibility
    ELSE 'private'::tour_visibility
END
WHERE visibility = 'private' AND is_public = true;

-- Add index for visibility filtering
CREATE INDEX IF NOT EXISTS idx_tours_visibility ON tours(visibility);

-- Add composite index for public tour queries
CREATE INDEX IF NOT EXISTS idx_tours_status_visibility ON tours(status, visibility) WHERE deleted_at IS NULL;

-- Note: We keep the is_public column for backward compatibility
-- It can be removed in a future migration after all clients are updated
COMMENT ON COLUMN tours.is_public IS 'DEPRECATED: Use visibility column instead. Will be removed in future migration.';
COMMENT ON COLUMN tours.visibility IS 'Tour access control: private (owner only), unlisted (direct link only), public (indexed and searchable)';
