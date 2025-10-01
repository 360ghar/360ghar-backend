BEGIN;

-- Add floor_plan_url and video_tour_url columns to properties table
ALTER TABLE properties
    ADD COLUMN floor_plan_url TEXT,
    ADD COLUMN video_tour_url TEXT;

COMMIT;
