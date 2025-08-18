-- Migration to add full-text search capabilities to the properties table.

-- 1. Add the tsvector column to the properties table
ALTER TABLE public.properties
ADD COLUMN __ts_vector__ tsvector;

-- 2. Create a GIN index on the new tsvector column for performance
CREATE INDEX idx_property_ts_vector
ON public.properties
USING GIN (__ts_vector__);

-- 3. Create a function to update the __ts_vector__ column
CREATE OR REPLACE FUNCTION properties_ts_vector_update()
RETURNS TRIGGER AS $$
BEGIN
    NEW.__ts_vector__ = (
        setweight(to_tsvector('english', coalesce(NEW.title, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(NEW.description, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(NEW.full_address, '')), 'C') ||
        setweight(to_tsvector('english', coalesce(NEW.city, '')), 'C') ||
        setweight(to_tsvector('english', coalesce(NEW.locality, '')), 'C')
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 4. Create a trigger to automatically call the function on insert or update
CREATE TRIGGER ts_vector_update
BEFORE INSERT OR UPDATE OF title, description, full_address, city, locality
ON public.properties
FOR EACH ROW
EXECUTE FUNCTION properties_ts_vector_update();

-- 5. Backfill the __ts_vector__ for existing data
-- This ensures that all properties are searchable immediately after migration.
UPDATE public.properties
SET __ts_vector__ = (
    setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
    setweight(to_tsvector('english', coalesce(description, '')), 'B') ||
    setweight(to_tsvector('english', coalesce(full_address, '')), 'C') ||
    setweight(to_tsvector('english', coalesce(city, '')), 'C') ||
    setweight(to_tsvector('english', coalesce(locality, '')), 'C')
)
WHERE __ts_vector__ IS NULL;

-- Add a comment to the new column for documentation
COMMENT ON COLUMN public.properties.__ts_vector__ IS 'Pre-computed tsvector for full-text search on property details.';
