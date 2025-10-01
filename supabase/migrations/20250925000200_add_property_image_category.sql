BEGIN;

-- Create image_category enum type
CREATE TYPE image_category AS ENUM (
    'room',
    'hall',
    'kitchen',
    'bathroom',
    'balcony',
    'terrace',
    'garden',
    'parking',
    'entrance',
    'exterior',
    'interior',
    'others'
);

-- Add image_category column to property_images table with default 'others'
ALTER TABLE property_images
    ADD COLUMN image_category image_category DEFAULT 'others' NOT NULL;

-- Create index on image_category for better query performance
CREATE INDEX idx_property_images_category ON property_images(image_category);

COMMIT;
