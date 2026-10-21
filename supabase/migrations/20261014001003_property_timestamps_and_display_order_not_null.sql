-- Timestamps and display order are NOT NULL on the property tables, to match the ORM and the
-- response schemas (conventions-26). Rows with a NULL value are filled first.
-- The BEFORE UPDATE updated_at triggers are switched off around the backfill. They set
-- updated_at to now(), which would replace created_at on every backfilled row.
-- Idempotent: each UPDATE matches only NULL rows, and SET NOT NULL and SET DEFAULT repeat safely.

-- properties
DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'update_properties_updated_at' AND tgrelid = 'properties'::regclass) THEN ALTER TABLE properties DISABLE TRIGGER update_properties_updated_at; END IF; END $$;
UPDATE properties SET created_at = now() WHERE created_at IS NULL;
UPDATE properties SET updated_at = created_at WHERE updated_at IS NULL;
DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'update_properties_updated_at' AND tgrelid = 'properties'::regclass) THEN ALTER TABLE properties ENABLE TRIGGER update_properties_updated_at; END IF; END $$;
ALTER TABLE properties
    ALTER COLUMN created_at SET DEFAULT now(),
    ALTER COLUMN created_at SET NOT NULL,
    ALTER COLUMN updated_at SET DEFAULT now(),
    ALTER COLUMN updated_at SET NOT NULL;

-- property_images
UPDATE property_images SET display_order = 0 WHERE display_order IS NULL;
UPDATE property_images SET created_at = now() WHERE created_at IS NULL;
DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'update_property_images_updated_at' AND tgrelid = 'property_images'::regclass) THEN ALTER TABLE property_images DISABLE TRIGGER update_property_images_updated_at; END IF; END $$;
UPDATE property_images SET updated_at = created_at WHERE updated_at IS NULL;
DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'update_property_images_updated_at' AND tgrelid = 'property_images'::regclass) THEN ALTER TABLE property_images ENABLE TRIGGER update_property_images_updated_at; END IF; END $$;
ALTER TABLE property_images
    ALTER COLUMN display_order SET DEFAULT 0,
    ALTER COLUMN display_order SET NOT NULL,
    ALTER COLUMN created_at SET DEFAULT now(),
    ALTER COLUMN created_at SET NOT NULL,
    ALTER COLUMN updated_at SET DEFAULT now(),
    ALTER COLUMN updated_at SET NOT NULL;

-- amenities
UPDATE amenities SET created_at = now() WHERE created_at IS NULL;
DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'update_amenities_updated_at' AND tgrelid = 'amenities'::regclass) THEN ALTER TABLE amenities DISABLE TRIGGER update_amenities_updated_at; END IF; END $$;
UPDATE amenities SET updated_at = created_at WHERE updated_at IS NULL;
DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'update_amenities_updated_at' AND tgrelid = 'amenities'::regclass) THEN ALTER TABLE amenities ENABLE TRIGGER update_amenities_updated_at; END IF; END $$;
ALTER TABLE amenities
    ALTER COLUMN created_at SET DEFAULT now(),
    ALTER COLUMN created_at SET NOT NULL,
    ALTER COLUMN updated_at SET DEFAULT now(),
    ALTER COLUMN updated_at SET NOT NULL;

-- property_amenities
UPDATE property_amenities SET created_at = now() WHERE created_at IS NULL;
ALTER TABLE property_amenities
    ALTER COLUMN created_at SET DEFAULT now(),
    ALTER COLUMN created_at SET NOT NULL;
