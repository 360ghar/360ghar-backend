-- ============================================================
-- 360Ghar Schema — 00: Extensions and shared functions
-- ============================================================
-- All extensions and reusable trigger functions used across
-- the entire schema live here so every subsequent migration
-- can depend on them unconditionally.
-- ============================================================

-- Required extensions
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ============================================================
-- Generic updated_at trigger function (used by most tables)
-- ============================================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ============================================================
-- Full-text search trigger for properties
-- Final version: includes search_keywords at weight B
-- ============================================================
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

-- ============================================================
-- Auto-populate PostGIS location from latitude/longitude
-- ============================================================
CREATE OR REPLACE FUNCTION trg_properties_set_location()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.location IS NULL AND NEW.latitude IS NOT NULL AND NEW.longitude IS NOT NULL THEN
        NEW.location := ST_SetSRID(ST_MakePoint(NEW.longitude, NEW.latitude), 4326);
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql VOLATILE;

-- ============================================================
-- Sync properties.owner_name from users.full_name
-- ============================================================
CREATE OR REPLACE FUNCTION public.sync_owner_name_on_user_rename()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    UPDATE public.properties
    SET owner_name = NEW.full_name
    WHERE owner_id = NEW.id
      AND owner_name IS DISTINCT FROM NEW.full_name;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.set_property_owner_name()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    owner_full_name TEXT;
BEGIN
    IF TG_OP = 'INSERT' OR NEW.owner_id IS DISTINCT FROM OLD.owner_id THEN
        SELECT full_name INTO owner_full_name FROM public.users WHERE id = NEW.owner_id;
        NEW.owner_name := owner_full_name;
    END IF;
    RETURN NEW;
END;
$$;
