-- ============================================================
-- 360Ghar Schema — 08: Flatmates social primitives
-- ============================================================
-- user_matches, user_blocks, user_reports, app_catalogs,
-- match_qna_answers, flatmate_profile_view_events,
-- flatmate_super_like_usage
-- ============================================================

-- ============================================================
-- User matches
-- ============================================================
CREATE TABLE user_matches (
    id BIGSERIAL PRIMARY KEY,
    user_one_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    user_two_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    context_property_id INTEGER REFERENCES properties(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ,
    CONSTRAINT ck_user_matches_status CHECK (status IN ('active', 'unmatched', 'blocked'))
);
CREATE UNIQUE INDEX idx_user_matches_unique_pair ON user_matches (user_one_id, user_two_id);
CREATE INDEX idx_user_matches_status ON user_matches (status);
CREATE TRIGGER update_user_matches_updated_at
    BEFORE UPDATE ON user_matches FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Link visits.match_id to user_matches
ALTER TABLE visits
    ADD CONSTRAINT visits_match_id_fkey
    FOREIGN KEY (match_id) REFERENCES user_matches(id) ON DELETE SET NULL;

-- ============================================================
-- User blocks
-- ============================================================
CREATE TABLE user_blocks (
    id BIGSERIAL PRIMARY KEY,
    blocker_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    blocked_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX idx_user_blocks_unique_pair ON user_blocks (blocker_user_id, blocked_user_id);

-- ============================================================
-- User reports (conversation_id FK → conversations)
-- ============================================================
CREATE TABLE user_reports (
    id BIGSERIAL PRIMARY KEY,
    reporter_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    reported_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    conversation_id BIGINT REFERENCES conversations(id) ON DELETE SET NULL,
    property_id INTEGER REFERENCES properties(id) ON DELETE SET NULL,
    reason TEXT NOT NULL DEFAULT 'other',
    status TEXT NOT NULL DEFAULT 'open',
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ,
    CONSTRAINT ck_user_reports_reason CHECK (reason IN ('spam', 'fake_profile', 'abuse', 'inappropriate', 'other')),
    CONSTRAINT ck_user_reports_status CHECK (status IN ('open', 'reviewed', 'dismissed', 'actioned'))
);
CREATE INDEX idx_user_reports_reported_user ON user_reports (reported_user_id, status);
CREATE INDEX idx_user_reports_reporter_user ON user_reports (reporter_user_id, created_at DESC);
CREATE TRIGGER update_user_reports_updated_at
    BEFORE UPDATE ON user_reports FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================
-- App catalogs (with final v2 lifestyle values seeded)
-- ============================================================
CREATE TABLE app_catalogs (
    id BIGSERIAL PRIMARY KEY,
    key TEXT NOT NULL UNIQUE,
    version INTEGER NOT NULL DEFAULT 1,
    payload JSONB NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ
);
CREATE INDEX idx_app_catalogs_active ON app_catalogs (is_active);
CREATE TRIGGER update_app_catalogs_updated_at
    BEFORE UPDATE ON app_catalogs FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Seed catalogs (final v2 values)
INSERT INTO app_catalogs (key, version, payload, is_active) VALUES
('flatmates_modes', 1, $${
    "items": [
        {"id": "co_hunter", "label": "Find a Flat / Flatmate", "description": "I want to find a place or a flatmate to stay with"},
        {"id": "room_poster", "label": "List My Flat / Find Flatmate", "description": "I want to list my flat or find a flatmate"},
        {"id": "open_to_both", "label": "Open to Both", "description": "I'm flexible, open to both finding a place and listing my flat"}
    ]
}$$::jsonb, TRUE),
('flatmates_move_in_timelines', 1, $${
    "items": [
        {"id": "immediately", "label": "Immediately"},
        {"id": "within_2_weeks", "label": "Within 2 Weeks"},
        {"id": "within_1_month", "label": "Within 1 Month"},
        {"id": "just_exploring", "label": "Just Exploring"}
    ]
}$$::jsonb, TRUE),
('flatmates_onboarding_quiz', 1, $${
    "dimensions": [
        {"id": "sleep_schedule", "label": "Sleep Schedule", "options": ["early_bird", "flexible", "night_owl"]},
        {"id": "cleanliness", "label": "Cleanliness", "options": ["minimal", "tidy", "spotless"]},
        {"id": "food_habits", "label": "Food Habits", "options": ["vegetarian", "vegan", "eggetarian", "non_vegetarian", "no_preference"]},
        {"id": "smoking_drinking", "label": "Smoking / Drinking", "options": ["neither", "smoke_outside", "drink_occasionally", "both_fine"]},
        {"id": "guests_policy", "label": "Guests Policy", "options": ["no_overnight_guests", "occasional_ok", "open_house"]},
        {"id": "work_style", "label": "Work Style", "options": ["wfh", "office", "hybrid"]}
    ]
}$$::jsonb, TRUE),
('flatmates_vibe_tags', 1, $${
    "items": ["Bachelor-friendly", "Quiet", "Active Community", "Family-dominant", "Pet-friendly", "Visitor-friendly"]
}$$::jsonb, TRUE),
('flatmates_popular_cities', 1, $${
    "items": [
        {"id": "bangalore", "label": "Bangalore", "state": "Karnataka"},
        {"id": "hyderabad", "label": "Hyderabad", "state": "Telangana"},
        {"id": "pune", "label": "Pune", "state": "Maharashtra"},
        {"id": "chennai", "label": "Chennai", "state": "Tamil Nadu"},
        {"id": "mumbai", "label": "Mumbai", "state": "Maharashtra"}
    ]
}$$::jsonb, TRUE),
('flatmates_room_types', 1, $${
    "items": [
        {"id": "private_room", "label": "Private Room"},
        {"id": "shared_room", "label": "Shared Room"},
        {"id": "master_bedroom", "label": "Master Bedroom"}
    ]
}$$::jsonb, TRUE),
('flatmates_society_types', 1, $${
    "items": [
        {"id": "gated", "label": "Gated Society"},
        {"id": "independent", "label": "Independent Building"},
        {"id": "co_living", "label": "Co-living"},
        {"id": "pg", "label": "PG"}
    ]
}$$::jsonb, TRUE),
('flatmates_flat_configs', 1, $${
    "items": [
        {"id": "1BHK", "label": "1 BHK"},
        {"id": "2BHK", "label": "2 BHK"},
        {"id": "3BHK", "label": "3 BHK"},
        {"id": "4BHK+", "label": "4 BHK+"},
        {"id": "studio", "label": "Studio"}
    ]
}$$::jsonb, TRUE),
('flatmates_listing_amenities', 1, $${
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
        {"id": "ac", "label": "AC"}
    ]
}$$::jsonb, TRUE),
('flatmates_non_negotiables', 1, $${
    "items": [
        {"id": "food_veg_only", "label": "Vegetarian only"},
        {"id": "no_smoking", "label": "No smoking"},
        {"id": "no_drinking", "label": "No drinking"},
        {"id": "no_overnight_guests", "label": "No overnight guests"},
        {"id": "no_pets", "label": "No pets"},
        {"id": "no_parties", "label": "No parties"},
        {"id": "min_tidy", "label": "Keeps common areas tidy"}
    ]
}$$::jsonb, TRUE),
('flatmates_report_reasons', 1, $${
    "items": [
        {"id": "spam", "label": "Spam"},
        {"id": "fake_profile", "label": "Fake Profile"},
        {"id": "abuse", "label": "Abuse"},
        {"id": "inappropriate", "label": "Inappropriate Content"},
        {"id": "other", "label": "Other"}
    ]
}$$::jsonb, TRUE),
('flatmates_lifestyle_quiz', 2, $${
    "questions": [
        {"id": "q1", "text": "What time do you usually wake up?", "dimension": "sleep_schedule", "options": [{"id": "early_bird", "label": "Early bird (before 7 AM)"}, {"id": "flexible", "label": "Flexible (7 - 9 AM)"}, {"id": "night_owl", "label": "Night owl (after 9 AM)"}]},
        {"id": "q2", "text": "How tidy are you?", "dimension": "cleanliness", "options": [{"id": "minimal", "label": "Minimal - lived-in is fine"}, {"id": "tidy", "label": "Tidy - things in their place"}, {"id": "spotless", "label": "Spotless - everything pristine"}]},
        {"id": "q3", "text": "How often do you have guests over?", "dimension": "guests_policy", "options": [{"id": "no_overnight_guests", "label": "No overnight guests"}, {"id": "occasional_ok", "label": "Occasional guests are ok"}, {"id": "open_house", "label": "Open house - always welcome"}]},
        {"id": "q4", "text": "What best describes your food habits?", "dimension": "food_habits", "options": [{"id": "vegetarian", "label": "Vegetarian"}, {"id": "vegan", "label": "Vegan"}, {"id": "non_vegetarian", "label": "Non-Vegetarian"}, {"id": "eggetarian", "label": "Eggetarian"}, {"id": "no_preference", "label": "No Preference"}]},
        {"id": "q5", "text": "How do you feel about smoking / drinking at home?", "dimension": "smoking_drinking", "options": [{"id": "neither", "label": "Neither"}, {"id": "smoke_outside", "label": "Smoke outside only"}, {"id": "drink_occasionally", "label": "Drink occasionally"}, {"id": "both_fine", "label": "Both are fine"}]},
        {"id": "q6", "text": "What is your typical work setup?", "dimension": "work_style", "options": [{"id": "wfh", "label": "Work from home"}, {"id": "office", "label": "Go to office"}, {"id": "hybrid", "label": "Hybrid"}]}
    ]
}$$::jsonb, TRUE),
('flatmates_icebreakers', 1, $${
    "prompts": [
        {"id": "ib1", "text": "What's your go-to midnight snack?"},
        {"id": "ib2", "text": "Are you a morning person or a night owl?"},
        {"id": "ib3", "text": "What's one thing you can't live without at home?"},
        {"id": "ib4", "text": "Favourite way to unwind after work?"},
        {"id": "ib5", "text": "Do you prefer cooking or ordering in?"},
        {"id": "ib6", "text": "What's your weekend usually look like?"},
        {"id": "ib7", "text": "Netflix, Prime, or something else?"},
        {"id": "ib8", "text": "What kind of music do you listen to?"},
        {"id": "ib9", "text": "Do you like having people over?"},
        {"id": "ib10", "text": "Early bird or snooze-button person?"}
    ]
}$$::jsonb, TRUE),
('flatmates_work_styles', 2, $${
    "items": [{"id": "wfh", "label": "Work from Home"}, {"id": "office", "label": "Office"}, {"id": "hybrid", "label": "Hybrid"}]
}$$::jsonb, TRUE),
('flatmates_gender_options', 1, $${
    "items": [{"id": "no_preference", "label": "No Preference"}, {"id": "male_only", "label": "Male Only"}, {"id": "female_only", "label": "Female Only"}, {"id": "other", "label": "Other"}]
}$$::jsonb, TRUE),
('flatmates_food_habits', 2, $${
    "items": [{"id": "vegetarian", "label": "Vegetarian"}, {"id": "non_vegetarian", "label": "Non-Vegetarian"}, {"id": "eggetarian", "label": "Eggetarian"}, {"id": "no_preference", "label": "No Preference"}]
}$$::jsonb, TRUE),
('flatmates_pets_options', 2, $${
    "items": [{"id": "have_pets", "label": "Yes, I have pets"}, {"id": "no_pets", "label": "No pets"}, {"id": "pet_friendly", "label": "Pet-friendly"}]
}$$::jsonb, TRUE),
('flatmates_smoking_options', 2, $${
    "items": [{"id": "neither", "label": "Neither"}, {"id": "smoke_outside", "label": "Smoke Outside"}, {"id": "drink_occasionally", "label": "Drink Occasionally"}, {"id": "both_fine", "label": "Both Fine"}]
}$$::jsonb, TRUE),
('flatmates_furnishing', 1, $${
    "items": [{"id": "any", "label": "Any"}, {"id": "furnished", "label": "Furnished"}, {"id": "semi_furnished", "label": "Semi Furnished"}, {"id": "unfurnished", "label": "Unfurnished"}]
}$$::jsonb, TRUE)
ON CONFLICT (key) DO NOTHING;

-- ============================================================
-- Match Q&A answers
-- ============================================================
CREATE TABLE match_qna_answers (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    match_id    BIGINT NOT NULL REFERENCES user_matches(id) ON DELETE CASCADE,
    user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    q1          TEXT,
    q2          VARCHAR(32),
    q3          TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_match_qna_match ON match_qna_answers (match_id);
CREATE UNIQUE INDEX idx_match_qna_unique_user_match ON match_qna_answers (match_id, user_id);

-- ============================================================
-- Flatmate profile view events
-- ============================================================
CREATE TABLE flatmate_profile_view_events (
    id                   BIGSERIAL PRIMARY KEY,
    viewer_user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    viewed_user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    context_property_id  INTEGER REFERENCES properties(id) ON DELETE SET NULL,
    source               VARCHAR(64) NOT NULL DEFAULT 'swipe_deck',
    duration_seconds     INTEGER NOT NULL DEFAULT 0,
    scroll_depth_percent INTEGER,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_flatmate_profile_views_viewer ON flatmate_profile_view_events (viewer_user_id, created_at DESC);
CREATE INDEX idx_flatmate_profile_views_viewed ON flatmate_profile_view_events (viewed_user_id, created_at DESC);
CREATE INDEX idx_flatmate_profile_views_property ON flatmate_profile_view_events (context_property_id, created_at DESC);

-- ============================================================
-- Flatmate super like usage
-- ============================================================
CREATE TABLE flatmate_super_like_usage (
    id BIGSERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    target_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    used_on DATE NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_flatmate_super_like_usage_target_day
        UNIQUE (user_id, target_user_id, used_on)
);
CREATE INDEX idx_flatmate_super_like_usage_user_day ON flatmate_super_like_usage (user_id, used_on);
