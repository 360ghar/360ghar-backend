-- Migration to add a geography column to the properties table for efficient geospatial queries.

-- Ensure the postgis extension is enabled
CREATE EXTENSION IF NOT EXISTS postgis;

-- Add the new geography column to the properties table
ALTER TABLE public.properties
ADD COLUMN location geography(POINT, 4326);

-- Create a GIST index on the new geography column for performance
CREATE INDEX idx_property_location_gist
ON public.properties
USING GIST (location);

-- Drop the old, inefficient index on latitude and longitude columns
DROP INDEX IF EXISTS idx_property_location;

-- Add a comment to the new column for documentation
COMMENT ON COLUMN public.properties.location IS 'Geospatial location of the property as a PostGIS geography point (SRID 4326).';
