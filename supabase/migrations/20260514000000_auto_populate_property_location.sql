-- Migration: Auto-populate PostGIS location from latitude/longitude on properties.
-- Adds a trigger that sets `location` from (longitude, latitude) whenever a property
-- is inserted or updated and the location column is NULL but lat/lng are present.
-- Also backfills all existing rows.

-- 1. Backfill existing properties that have lat/lng but no location
UPDATE properties
SET location = ST_SetSRID(ST_MakePoint(longitude, latitude), 4326)
WHERE latitude IS NOT NULL
  AND longitude IS NOT NULL
  AND location IS NULL;

-- 2. Create the trigger function
CREATE OR REPLACE FUNCTION trg_properties_set_location()
RETURNS TRIGGER AS $$
BEGIN
    -- Only compute when location is NULL and both coordinates are present
    IF NEW.location IS NULL AND NEW.latitude IS NOT NULL AND NEW.longitude IS NOT NULL THEN
        NEW.location := ST_SetSRID(ST_MakePoint(NEW.longitude, NEW.latitude), 4326);
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql VOLATILE;

-- 3. Attach the trigger to fire before INSERT and UPDATE
DROP TRIGGER IF EXISTS properties_set_location_trigger ON properties;
CREATE TRIGGER properties_set_location_trigger
    BEFORE INSERT OR UPDATE OF latitude, longitude ON properties
    FOR EACH ROW
    EXECUTE FUNCTION trg_properties_set_location();
