-- Migration to include search_keywords in the full-text search trigger.
-- Previously, search_keywords was excluded from the tsvector computation,
-- so property owners who added search keywords got no FTS benefit.

-- 1. Update the trigger function to include search_keywords with weight B
CREATE OR REPLACE FUNCTION properties_ts_vector_update()
RETURNS TRIGGER AS $$
BEGIN
    NEW.__ts_vector__ = (
        setweight(to_tsvector('english', coalesce(NEW.title, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(NEW.description, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(NEW.search_keywords, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(NEW.full_address, '')), 'C') ||
        setweight(to_tsvector('english', coalesce(NEW.city, '')), 'C') ||
        setweight(to_tsvector('english', coalesce(NEW.locality, '')), 'C')
    );
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 2. Update the trigger to also fire on search_keywords changes
DROP TRIGGER IF EXISTS ts_vector_update ON public.properties;
CREATE TRIGGER ts_vector_update
BEFORE INSERT OR UPDATE OF title, description, search_keywords, full_address, city, locality
ON public.properties
FOR EACH ROW
EXECUTE FUNCTION properties_ts_vector_update();

-- 3. Backfill tsvector for all existing properties to include search_keywords
UPDATE public.properties
SET __ts_vector__ = (
    setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
    setweight(to_tsvector('english', coalesce(description, '')), 'B') ||
    setweight(to_tsvector('english', coalesce(search_keywords, '')), 'B') ||
    setweight(to_tsvector('english', coalesce(full_address, '')), 'C') ||
    setweight(to_tsvector('english', coalesce(city, '')), 'C') ||
    setweight(to_tsvector('english', coalesce(locality, '')), 'C')
);
