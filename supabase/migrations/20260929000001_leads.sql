-- =============================================================================
-- Leads: callback requests from the property page
-- Migration: 20260929000001_leads.sql
--
-- POST /api/v1/leads stores a mobile number and an optional note, for a
-- property, from a visitor who may not be signed in. phone holds the 10-digit
-- Indian mobile number. Rows keep no FK cascade: deleting a property or a user
-- leaves the lead with a NULL reference.
-- =============================================================================

CREATE TABLE IF NOT EXISTS leads (
    id          SERIAL PRIMARY KEY,
    property_id INTEGER REFERENCES properties (id) ON DELETE SET NULL,
    user_id     INTEGER REFERENCES users (id) ON DELETE SET NULL,
    name        VARCHAR(100),
    phone       VARCHAR(10) NOT NULL,
    note        VARCHAR(500),
    source      VARCHAR(30) NOT NULL DEFAULT 'property_page',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_leads_property_id ON leads (property_id);
CREATE INDEX IF NOT EXISTS idx_leads_phone ON leads (phone);
CREATE INDEX IF NOT EXISTS idx_leads_created_at ON leads (created_at DESC);

-- The API connects with the service role; block direct client access.
ALTER TABLE leads ENABLE ROW LEVEL SECURITY;
