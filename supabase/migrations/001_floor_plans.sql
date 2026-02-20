-- ================================================================
-- 001_floor_plans.sql
-- Creates the floor_plans table for 360 Virtual Tour Platform
--
-- IMPORTANT:
-- This file intentionally avoids hard dependencies on other migrations so it
-- can be executed standalone. The canonical/complete schema is finalized in
-- `20260112000000_fix_360_viewer_schema.sql`.
-- ================================================================

-- Floor Plans Table
-- Stores floor plan images and scene markers for virtual tours
DO $$ BEGIN
    IF to_regclass('public.floor_plans') IS NULL THEN
        CREATE TABLE floor_plans (
            id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
            tour_id VARCHAR(36) NOT NULL,
            name VARCHAR(255) NOT NULL DEFAULT 'Floor Plan',
            image_url TEXT NOT NULL,
            floor_number INTEGER DEFAULT 1,
            markers JSONB DEFAULT '[]'::jsonb,
            created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
            updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
        );
    END IF;
END $$;

-- Add FK only when `tours` exists (avoids ordering failures on fresh DBs).
DO $$ BEGIN
    IF to_regclass('public.tours') IS NOT NULL THEN
        BEGIN
            ALTER TABLE floor_plans
                ADD CONSTRAINT floor_plans_tour_id_fkey
                FOREIGN KEY (tour_id) REFERENCES tours(id) ON DELETE CASCADE;
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END;
    END IF;
END $$;

-- Index for efficient tour lookups
CREATE INDEX IF NOT EXISTS idx_floor_plans_tour_id ON floor_plans(tour_id);


-- Ensure the update_updated_at_column function exists
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Trigger to auto-update updated_at on changes
DROP TRIGGER IF EXISTS update_floor_plans_updated_at ON floor_plans;
CREATE TRIGGER update_floor_plans_updated_at
    BEFORE UPDATE ON floor_plans
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Add comments for documentation
COMMENT ON TABLE floor_plans IS 'Floor plan images and scene markers for virtual tours';
COMMENT ON COLUMN floor_plans.id IS 'Unique identifier for the floor plan';
COMMENT ON COLUMN floor_plans.tour_id IS 'Reference to the parent tour';
COMMENT ON COLUMN floor_plans.name IS 'Display name for the floor (e.g., "Ground Floor", "First Floor")';
COMMENT ON COLUMN floor_plans.image_url IS 'URL to the floor plan image';
COMMENT ON COLUMN floor_plans.floor_number IS 'Order/level of the floor (1-based)';
COMMENT ON COLUMN floor_plans.markers IS 'JSON array of scene markers: [{scene_id, x, y, label}]';

-- Enable Row Level Security (optional, for multi-tenant access)
-- ALTER TABLE floor_plans ENABLE ROW LEVEL SECURITY;

-- RLS Policy: Users can only access floor plans of tours they own
-- CREATE POLICY floor_plans_owner_policy ON floor_plans
--     USING (tour_id IN (SELECT id FROM tours WHERE user_id = auth.uid()));

-- ================================================================
-- Verification query (run after migration)
-- ================================================================
-- SELECT column_name, data_type, is_nullable
-- FROM information_schema.columns
-- WHERE table_name = 'floor_plans';
