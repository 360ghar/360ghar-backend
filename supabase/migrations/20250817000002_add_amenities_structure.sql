-- Migration to add amenities structure and remove JSON amenities field
-- Date: 2025-08-17
-- Description: Replace properties.amenities JSON field with proper amenities table and many-to-many relationship

-- Step 1: Create amenities table
CREATE TABLE IF NOT EXISTS amenities (
    id SERIAL PRIMARY KEY,
    title VARCHAR(100) NOT NULL UNIQUE,
    icon VARCHAR(100),
    category VARCHAR(50),
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITHOUT TIME ZONE
);

-- Step 2: Create property_amenities junction table
CREATE TABLE IF NOT EXISTS property_amenities (
    id SERIAL PRIMARY KEY,
    property_id INTEGER NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    amenity_id INTEGER NOT NULL REFERENCES amenities(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT NOW(),
    UNIQUE(property_id, amenity_id)
);

-- Step 3: Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_amenities_category ON amenities(category);
CREATE INDEX IF NOT EXISTS idx_amenities_is_active ON amenities(is_active);
CREATE INDEX IF NOT EXISTS idx_property_amenities_property ON property_amenities(property_id);
CREATE INDEX IF NOT EXISTS idx_property_amenities_amenity ON property_amenities(amenity_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_property_amenity_unique ON property_amenities(property_id, amenity_id);

-- Step 4: Insert predefined amenities
INSERT INTO amenities (title, icon, category) VALUES
-- Safety & Security
('Security', 'shield-check', 'safety'),
('CCTV', 'camera', 'safety'),
('Gated Community', 'gate', 'safety'),
('24/7 Security', 'clock', 'safety'),
('Intercom', 'phone', 'safety'),
('Fire Safety', 'fire', 'safety'),

-- Recreation & Entertainment
('Swimming Pool', 'pool', 'recreation'),
('Gym', 'dumbbell', 'recreation'),
('Fitness Center', 'fitness', 'recreation'),
('Clubhouse', 'building', 'recreation'),
('Children''s Play Area', 'playground', 'recreation'),
('Sports Court', 'tennis-ball', 'recreation'),
('Jogging Track', 'running', 'recreation'),
('Garden', 'tree', 'recreation'),
('Park', 'park', 'recreation'),

-- Convenience & Utilities
('Parking', 'car', 'convenience'),
('Covered Parking', 'garage', 'convenience'),
('Lift', 'elevator', 'convenience'),
('Elevator', 'elevator', 'convenience'),
('Power Backup', 'battery', 'utilities'),
('Generator', 'generator', 'utilities'),
('Water Supply', 'water', 'utilities'),
('Borewell', 'drill', 'utilities'),
('Rainwater Harvesting', 'droplets', 'utilities'),
('Waste Management', 'trash', 'utilities'),
('Maintenance', 'tools', 'services'),

-- Modern Amenities
('WiFi', 'wifi', 'convenience'),
('Internet', 'internet', 'convenience'),
('Cable TV', 'tv', 'convenience'),
('Air Conditioning', 'ac', 'convenience'),
('Central AC', 'ac-central', 'convenience'),
('Heating', 'thermometer', 'convenience'),

-- Services
('Concierge', 'user-tie', 'services'),
('Housekeeping', 'broom', 'services'),
('Laundry', 'washing-machine', 'services'),
('Grocery Store', 'shopping-cart', 'services'),
('Medical Center', 'medical', 'services'),

-- Accessibility
('Wheelchair Accessible', 'wheelchair', 'accessibility'),
('Senior Friendly', 'elderly', 'accessibility'),
('Pet Friendly', 'pet', 'accessibility'),

-- Location Benefits
('Metro Connectivity', 'train', 'convenience'),
('Bus Stop Nearby', 'bus', 'convenience'),
('Airport Nearby', 'plane', 'convenience'),
('Mall Nearby', 'shopping-bag', 'convenience'),
('School Nearby', 'school', 'convenience'),
('Hospital Nearby', 'hospital', 'convenience')
ON CONFLICT (title) DO NOTHING;

-- Step 5: Migrate existing amenities data from properties.amenities JSON to property_amenities table
-- Note: This migration assumes that existing amenities data exists as JSON array of strings
-- We'll create a function to handle this migration if data exists

CREATE OR REPLACE FUNCTION migrate_property_amenities() RETURNS void AS $$
DECLARE
    prop_record RECORD;
    amenity_name TEXT;
    amenity_id INTEGER;
BEGIN
    -- Loop through properties that have amenities data
    FOR prop_record IN 
        SELECT id, amenities 
        FROM properties 
        WHERE amenities IS NOT NULL 
        AND jsonb_array_length(amenities::jsonb) > 0
    LOOP
        -- Loop through each amenity in the JSON array
        FOR amenity_name IN 
            SELECT jsonb_array_elements_text(prop_record.amenities::jsonb)
        LOOP
            -- Find matching amenity by title (case insensitive)
            SELECT id INTO amenity_id 
            FROM amenities 
            WHERE LOWER(title) = LOWER(amenity_name) 
            OR LOWER(title) LIKE '%' || LOWER(amenity_name) || '%'
            LIMIT 1;
            
            -- If amenity found, create the relationship
            IF amenity_id IS NOT NULL THEN
                INSERT INTO property_amenities (property_id, amenity_id)
                VALUES (prop_record.id, amenity_id)
                ON CONFLICT (property_id, amenity_id) DO NOTHING;
            END IF;
        END LOOP;
    END LOOP;
END;
$$ LANGUAGE plpgsql;

-- Execute the migration function
SELECT migrate_property_amenities();

-- Drop the migration function as it's no longer needed
DROP FUNCTION migrate_property_amenities();

-- Step 6: Remove the amenities column from properties table
ALTER TABLE properties DROP COLUMN IF EXISTS amenities;

-- Step 7: Add updated_at trigger for amenities table
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_amenities_updated_at 
    BEFORE UPDATE ON amenities 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();