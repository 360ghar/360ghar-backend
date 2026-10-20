-- Timestamps and display order are NOT NULL on the property tables, to match the ORM and the
-- response schemas (conventions-26). Rows with a NULL value are filled first.
-- Idempotent: each UPDATE matches only NULL rows, and SET NOT NULL and SET DEFAULT repeat safely.

-- properties
UPDATE properties SET created_at = now() WHERE created_at IS NULL;
UPDATE properties SET updated_at = created_at WHERE updated_at IS NULL;
ALTER TABLE properties
    ALTER COLUMN created_at SET DEFAULT now(),
    ALTER COLUMN created_at SET NOT NULL,
    ALTER COLUMN updated_at SET DEFAULT now(),
    ALTER COLUMN updated_at SET NOT NULL;

-- property_images
UPDATE property_images SET display_order = 0 WHERE display_order IS NULL;
UPDATE property_images SET created_at = now() WHERE created_at IS NULL;
UPDATE property_images SET updated_at = created_at WHERE updated_at IS NULL;
ALTER TABLE property_images
    ALTER COLUMN display_order SET DEFAULT 0,
    ALTER COLUMN display_order SET NOT NULL,
    ALTER COLUMN created_at SET DEFAULT now(),
    ALTER COLUMN created_at SET NOT NULL,
    ALTER COLUMN updated_at SET DEFAULT now(),
    ALTER COLUMN updated_at SET NOT NULL;

-- amenities
UPDATE amenities SET created_at = now() WHERE created_at IS NULL;
UPDATE amenities SET updated_at = created_at WHERE updated_at IS NULL;
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
