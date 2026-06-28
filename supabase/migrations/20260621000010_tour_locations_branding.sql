-- ============================================================
-- 360Ghar Schema — 10: Tour locations and branding
-- ============================================================
-- Adds tour_locations and tour_branding tables referenced by
-- ORM models but missing from the consolidated migrations.
-- ============================================================

-- ============================================================
-- Tour locations: geographic metadata for tours
-- ============================================================
CREATE TABLE tour_locations (
    id              VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
    tour_id         VARCHAR(36) NOT NULL REFERENCES tours(id) ON DELETE CASCADE,
    name            VARCHAR(255),
    address         TEXT,
    city            VARCHAR(100),
    state           VARCHAR(100),
    country         VARCHAR(100),
    postal_code     VARCHAR(20),
    latitude        DOUBLE PRECISION,
    longitude       DOUBLE PRECISION,
    timezone        VARCHAR(50),
    elevation       DOUBLE PRECISION,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_locations_tour_id ON tour_locations(tour_id);
CREATE INDEX idx_locations_country_city ON tour_locations(country, city);
CREATE TRIGGER update_tour_locations_updated_at
    BEFORE UPDATE ON tour_locations FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================
-- Tour branding: per-tour branding/whitelabel config
-- ============================================================
CREATE TABLE tour_branding (
    id              VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
    tour_id         VARCHAR(36) NOT NULL REFERENCES tours(id) ON DELETE CASCADE,
    settings        JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_tour_branding_tour_id ON tour_branding(tour_id);
CREATE TRIGGER update_tour_branding_updated_at
    BEFORE UPDATE ON tour_branding FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
