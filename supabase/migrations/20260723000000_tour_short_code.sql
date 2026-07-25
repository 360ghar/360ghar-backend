-- =============================================================================
-- Virtual Tours – short share codes
-- Migration: 20260723000000_tour_short_code.sql
--
-- Adds a nullable short_code column to tours for compact share links
-- (GET /v/{code}). Codes are assigned on first publish and never cleared,
-- so existing links keep working across unpublish/republish cycles.
--
-- Uniqueness is enforced by a partial unique index (NULLs excluded) since
-- most historical rows have no code.
-- =============================================================================

ALTER TABLE tours ADD COLUMN IF NOT EXISTS short_code VARCHAR(12);

CREATE UNIQUE INDEX IF NOT EXISTS idx_tours_short_code ON tours (short_code) WHERE short_code IS NOT NULL;
