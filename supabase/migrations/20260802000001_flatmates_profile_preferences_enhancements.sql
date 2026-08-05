-- ============================================================
-- 360Ghar Schema — Flatmates profile / preferences / property enhancements
-- ============================================================
-- New lifestyle dimensions (smoking + drinking split, 3 levels each),
-- privacy-bucket age storage, native place / LinkedIn, and new property
-- detail columns (kitchen, ventilation, windows, charges, furnishing).
-- ============================================================

-- ============================================================
-- Enum types
-- ============================================================
-- Postgres has no CREATE TYPE IF NOT EXISTS; wrap in a DO block so the
-- migration stays idempotent (schema_migrations guard is the primary
-- protection, this is belt-and-suspenders for partial re-runs).
DO $$
BEGIN
    CREATE TYPE flatmates_smoking_type AS ENUM ('never', 'occasionally', 'regularly');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
    CREATE TYPE flatmates_drinking_type AS ENUM ('never', 'occasionally', 'regularly');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
    CREATE TYPE property_kitchen_type AS ENUM ('vegetarian', 'non_vegetarian', 'eggetarian', 'any');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
    CREATE TYPE property_ventilation_type AS ENUM ('good', 'average', 'poor');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

-- ============================================================
-- Users: split lifestyle dimensions + new profile fields
-- ============================================================
ALTER TABLE users ADD COLUMN IF NOT EXISTS flatmates_smoking flatmates_smoking_type;
ALTER TABLE users ADD COLUMN IF NOT EXISTS flatmates_drinking flatmates_drinking_type;
ALTER TABLE users ADD COLUMN IF NOT EXISTS native_place VARCHAR(120);
ALTER TABLE users ADD COLUMN IF NOT EXISTS linkedin_url VARCHAR(255);
-- Denormalized age used for filtering; the exact age is never exposed to
-- clients — the server derives a privacy bucket from it (bucket logic in B2).
ALTER TABLE users ADD COLUMN IF NOT EXISTS flatmates_age INTEGER;

-- Lifestyle reset decision: the single combined flatmates_smoking_drinking
-- enum is replaced by two independent dimensions (smoking, drinking), each
-- with levels never/occasionally/regularly. All previously collected
-- combined lifestyle values are reset to NULL. The old column and its enum
-- type are intentionally KEPT (no DROP) so already-shipped app builds that
-- still write/read flatmates_smoking_drinking do not break; new code stops
-- using it.
UPDATE users SET flatmates_smoking_drinking = NULL;

-- Backfill flatmates_age:
--   1. From preferences JSONB path {flatmates,age} — a numeric string; cast
--      only when it matches ^[0-9]+$ and falls in the 18-100 sanity range.
--   2. Fall back to the age derived from date_of_birth where still NULL.
UPDATE users
SET flatmates_age = COALESCE(
    CASE
        WHEN preferences #>> '{flatmates,age}' ~ '^[0-9]+$'
             AND (preferences #>> '{flatmates,age}')::integer BETWEEN 18 AND 100
        THEN (preferences #>> '{flatmates,age}')::integer
    END,
    CASE
        WHEN date_of_birth IS NOT NULL THEN DATE_PART('year', AGE(date_of_birth))::integer
    END
)
WHERE flatmates_age IS NULL;

CREATE INDEX IF NOT EXISTS idx_users_flatmates_age
    ON users(flatmates_age) WHERE flatmates_age IS NOT NULL;

-- ============================================================
-- Properties: kitchen / ventilation / windows / charges / furnishing
-- ============================================================
ALTER TABLE properties ADD COLUMN IF NOT EXISTS kitchen_type property_kitchen_type;
ALTER TABLE properties ADD COLUMN IF NOT EXISTS ventilation_type property_ventilation_type;
ALTER TABLE properties ADD COLUMN IF NOT EXISTS windows_count INTEGER;
ALTER TABLE properties ADD COLUMN IF NOT EXISTS ventilation_shafts INTEGER;
ALTER TABLE properties ADD COLUMN IF NOT EXISTS setup_cost NUMERIC(12,2);
ALTER TABLE properties ADD COLUMN IF NOT EXISTS other_charges NUMERIC(12,2);
ALTER TABLE properties ADD COLUMN IF NOT EXISTS other_charges_description TEXT;
ALTER TABLE properties ADD COLUMN IF NOT EXISTS furnishing_level VARCHAR(32);

-- Backfill furnishing_level from the legacy features JSONB column, which is
-- stored in two shapes depending on which client wrote it:
--   1. object form: {"furnishing_level": "furnished", ...}
--      -> features->>'furnishing_level'
--   2. array form:  ["furnished", ...] (string list the client toggles)
--      -> first matching key wins: furnished > semi_furnished > unfurnished
UPDATE properties
SET furnishing_level = CASE
    WHEN jsonb_typeof(features) = 'object' THEN features->>'furnishing_level'
    WHEN jsonb_typeof(features) = 'array' THEN
        CASE
            WHEN features ? 'furnished' THEN 'furnished'
            WHEN features ? 'semi_furnished' THEN 'semi_furnished'
            WHEN features ? 'unfurnished' THEN 'unfurnished'
        END
    ELSE NULL
END
WHERE furnishing_level IS NULL;

CREATE INDEX IF NOT EXISTS idx_properties_furnishing_level
    ON properties(furnishing_level) WHERE furnishing_level IS NOT NULL;

-- ============================================================
-- Amenity seeds (idempotent on unique title)
-- ============================================================
-- 'Nearby Parks' is new; the rest already exist from migration 01 but are
-- re-inserted defensively (ON CONFLICT DO NOTHING) in case they were ever
-- removed on an environment.
INSERT INTO amenities (title, icon, category) VALUES
('Nearby Parks', 'tree-pine', 'recreation'),
('Air Conditioning', 'ac', 'convenience'),
('Parking', 'car', 'convenience'),
('Lift', 'elevator', 'convenience'),
('Power Backup', 'battery', 'utilities'),
('Garden', 'tree', 'recreation')
ON CONFLICT (title) DO NOTHING;

-- ============================================================
-- Catalog seeds (app_catalogs, key unique)
-- ============================================================
-- Upsert keeps catalogs current across environments: payload/version are
-- refreshed on conflict, new keys are inserted, is_active is forced on.

-- Move-in timeline: 7 canonical options (replaces the old 4-entry list)
INSERT INTO app_catalogs (key, version, payload, is_active) VALUES
('flatmates_move_in_timelines', 2, $${
    "items": [
        {"id": "immediately", "label": "Immediately"},
        {"id": "within_1_week", "label": "Within 1 Week"},
        {"id": "within_2_weeks", "label": "Within 2 Weeks"},
        {"id": "within_1_month", "label": "Within 1 Month"},
        {"id": "within_2_months", "label": "Within 2 Months"},
        {"id": "within_3_months", "label": "Within 3 Months"},
        {"id": "flexible", "label": "Flexible"}
    ]
}$$::jsonb, TRUE),
-- Smoking / drinking are now independent 3-level dimensions; this key
-- previously carried the combined values (neither/smoke_outside/...) and is
-- replaced wholesale.
('flatmates_smoking_options', 3, $${
    "items": [
        {"id": "never", "label": "Never"},
        {"id": "occasionally", "label": "Occasionally"},
        {"id": "regularly", "label": "Regularly"}
    ]
}$$::jsonb, TRUE),
('flatmates_drinking_options', 1, $${
    "items": [
        {"id": "never", "label": "Never"},
        {"id": "occasionally", "label": "Occasionally"},
        {"id": "regularly", "label": "Regularly"}
    ]
}$$::jsonb, TRUE),
('flatmates_kitchen_types', 1, $${
    "items": [
        {"id": "vegetarian", "label": "Vegetarian"},
        {"id": "non_vegetarian", "label": "Non-Vegetarian"},
        {"id": "eggetarian", "label": "Eggetarian"},
        {"id": "any", "label": "Any"}
    ]
}$$::jsonb, TRUE),
('flatmates_ventilation_options', 1, $${
    "items": [
        {"id": "good", "label": "Good"},
        {"id": "average", "label": "Average"},
        {"id": "poor", "label": "Poor"}
    ]
}$$::jsonb, TRUE),
-- Listing amenities: existing set preserved, new ids appended
('flatmates_listing_amenities', 2, $${
    "items": [
        {"id": "furnished", "label": "Furnished"},
        {"id": "semi_furnished", "label": "Semi Furnished"},
        {"id": "wifi", "label": "Wi-Fi"},
        {"id": "parking", "label": "Parking"},
        {"id": "security", "label": "24/7 Security"},
        {"id": "lift", "label": "Lift"},
        {"id": "washing_machine", "label": "Washing Machine"},
        {"id": "attached_bathroom", "label": "Attached Bathroom"},
        {"id": "balcony", "label": "Balcony"},
        {"id": "ac", "label": "AC"},
        {"id": "power_backup", "label": "Power Backup"},
        {"id": "nearby_parks", "label": "Nearby Parks"},
        {"id": "gym", "label": "Gym"},
        {"id": "cctv", "label": "CCTV"},
        {"id": "intercom", "label": "Intercom"},
        {"id": "garden", "label": "Garden"},
        {"id": "clubhouse", "label": "Clubhouse"}
    ]
}$$::jsonb, TRUE)
ON CONFLICT (key) DO UPDATE SET
    payload = excluded.payload,
    version = excluded.version,
    is_active = true;

-- Lifestyle quiz: the combined smoking/drinking question (q5) is replaced by
-- two independent questions; work_style moves to q7. Question shape
-- (id/text/dimension/options with id+label) is preserved.
INSERT INTO app_catalogs (key, version, payload, is_active) VALUES
('flatmates_lifestyle_quiz', 3, $${
    "questions": [
        {"id": "q1", "text": "What time do you usually wake up?", "dimension": "sleep_schedule", "options": [{"id": "early_bird", "label": "Early bird (before 7 AM)"}, {"id": "flexible", "label": "Flexible (7 - 9 AM)"}, {"id": "night_owl", "label": "Night owl (after 9 AM)"}]},
        {"id": "q2", "text": "How tidy are you?", "dimension": "cleanliness", "options": [{"id": "minimal", "label": "Minimal - lived-in is fine"}, {"id": "tidy", "label": "Tidy - things in their place"}, {"id": "spotless", "label": "Spotless - everything pristine"}]},
        {"id": "q3", "text": "How often do you have guests over?", "dimension": "guests_policy", "options": [{"id": "no_overnight_guests", "label": "No overnight guests"}, {"id": "occasional_ok", "label": "Occasional guests are ok"}, {"id": "open_house", "label": "Open house - always welcome"}]},
        {"id": "q4", "text": "What best describes your food habits?", "dimension": "food_habits", "options": [{"id": "vegetarian", "label": "Vegetarian"}, {"id": "vegan", "label": "Vegan"}, {"id": "non_vegetarian", "label": "Non-Vegetarian"}, {"id": "eggetarian", "label": "Eggetarian"}, {"id": "no_preference", "label": "No Preference"}]},
        {"id": "q5", "text": "How often do you smoke?", "dimension": "smoking", "options": [{"id": "never", "label": "Never"}, {"id": "occasionally", "label": "Occasionally"}, {"id": "regularly", "label": "Regularly"}]},
        {"id": "q6", "text": "How often do you drink?", "dimension": "drinking", "options": [{"id": "never", "label": "Never"}, {"id": "occasionally", "label": "Occasionally"}, {"id": "regularly", "label": "Regularly"}]},
        {"id": "q7", "text": "What is your typical work setup?", "dimension": "work_style", "options": [{"id": "wfh", "label": "Work from home"}, {"id": "office", "label": "Go to office"}, {"id": "hybrid", "label": "Hybrid"}]}
    ]
}$$::jsonb, TRUE),
-- Onboarding quiz mirrors the same split in its compact dimensions shape
('flatmates_onboarding_quiz', 2, $${
    "dimensions": [
        {"id": "sleep_schedule", "label": "Sleep Schedule", "options": ["early_bird", "flexible", "night_owl"]},
        {"id": "cleanliness", "label": "Cleanliness", "options": ["minimal", "tidy", "spotless"]},
        {"id": "food_habits", "label": "Food Habits", "options": ["vegetarian", "vegan", "eggetarian", "non_vegetarian", "no_preference"]},
        {"id": "smoking", "label": "Smoking", "options": ["never", "occasionally", "regularly"]},
        {"id": "drinking", "label": "Drinking", "options": ["never", "occasionally", "regularly"]},
        {"id": "guests_policy", "label": "Guests Policy", "options": ["no_overnight_guests", "occasional_ok", "open_house"]},
        {"id": "work_style", "label": "Work Style", "options": ["wfh", "office", "hybrid"]}
    ]
}$$::jsonb, TRUE)
ON CONFLICT (key) DO UPDATE SET
    payload = excluded.payload,
    version = excluded.version,
    is_active = true;
