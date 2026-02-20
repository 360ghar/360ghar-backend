-- Fix 360 Viewer schema drift (tours/scenes/hotspots/floor plans/analytics/uploads)
-- Safe to run on existing databases:
-- - Adds missing enum values/columns
-- - Fixes floor_plans type mismatch (UUID -> VARCHAR(36))
-- - Creates media_files table used by uploads APIs

-- =========================================================
-- 1) Hotspot enum and table columns
-- =========================================================

DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'hotspot_type') THEN
        BEGIN
            ALTER TYPE hotspot_type ADD VALUE IF NOT EXISTS 'link';
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END;
    ELSE
        CREATE TYPE hotspot_type AS ENUM ('navigation', 'info', 'audio', 'video', 'link', 'custom');
    END IF;
END $$;

ALTER TABLE IF EXISTS hotspots
    ADD COLUMN IF NOT EXISTS icon_name VARCHAR(100),
    ADD COLUMN IF NOT EXISTS content JSONB;

-- =========================================================
-- 2) Analytics event schema
-- =========================================================

ALTER TABLE IF EXISTS tour_analytics_events
    ADD COLUMN IF NOT EXISTS user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS event_data JSONB,
    ADD COLUMN IF NOT EXISTS city VARCHAR(100),
    ADD COLUMN IF NOT EXISTS browser VARCHAR(50),
    ADD COLUMN IF NOT EXISTS os VARCHAR(50),
    ADD COLUMN IF NOT EXISTS screen_resolution VARCHAR(20);

ALTER TABLE IF EXISTS tour_analytics_events
    ALTER COLUMN event_data SET DEFAULT '{}'::jsonb;

UPDATE tour_analytics_events
SET event_data = '{}'::jsonb
WHERE event_data IS NULL;

-- Allow longer session identifiers (frontend may use UUID or other ids)
ALTER TABLE IF EXISTS tour_analytics_events
    ALTER COLUMN session_id TYPE VARCHAR(255);

CREATE INDEX IF NOT EXISTS idx_analytics_user_id ON tour_analytics_events(user_id);

-- =========================================================
-- 3) Floor plans table (fix UUID vs VARCHAR mismatch)
-- =========================================================

DO $$
DECLARE
    fk RECORD;
    pkey_name TEXT;
BEGIN
    IF to_regclass('public.floor_plans') IS NULL THEN
        CREATE TABLE floor_plans (
            id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
            tour_id VARCHAR(36) NOT NULL REFERENCES tours(id) ON DELETE CASCADE,
            name VARCHAR(255) NOT NULL DEFAULT 'Floor Plan',
            image_url VARCHAR(512) NOT NULL,
            floor_number INTEGER DEFAULT 1,
            markers JSONB DEFAULT '[]'::jsonb,
            created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
            updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
        );
    ELSE
        -- Drop existing foreign keys (if any) so we can alter column types.
        FOR fk IN
            SELECT conname
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            WHERE t.relname = 'floor_plans' AND c.contype = 'f'
        LOOP
            EXECUTE format('ALTER TABLE floor_plans DROP CONSTRAINT IF EXISTS %I', fk.conname);
        END LOOP;

        -- If id is UUID, convert to VARCHAR(36) and re-create primary key.
        IF EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'floor_plans'
              AND column_name = 'id'
              AND data_type = 'uuid'
        ) THEN
            SELECT conname INTO pkey_name
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            WHERE t.relname = 'floor_plans' AND c.contype = 'p'
            LIMIT 1;

            IF pkey_name IS NOT NULL THEN
                EXECUTE format('ALTER TABLE floor_plans DROP CONSTRAINT IF EXISTS %I', pkey_name);
            END IF;

            EXECUTE 'ALTER TABLE floor_plans ALTER COLUMN id TYPE VARCHAR(36) USING id::text';
            EXECUTE 'ALTER TABLE floor_plans ALTER COLUMN id SET DEFAULT gen_random_uuid()::text';
            EXECUTE 'ALTER TABLE floor_plans ADD CONSTRAINT floor_plans_pkey PRIMARY KEY (id)';
        END IF;

        -- If tour_id is UUID, convert to VARCHAR(36).
        IF EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'floor_plans'
              AND column_name = 'tour_id'
              AND data_type = 'uuid'
        ) THEN
            EXECUTE 'ALTER TABLE floor_plans ALTER COLUMN tour_id TYPE VARCHAR(36) USING tour_id::text';
        END IF;

        -- Ensure expected defaults.
        BEGIN
            EXECUTE 'ALTER TABLE floor_plans ALTER COLUMN id SET DEFAULT gen_random_uuid()::text';
        EXCEPTION
            WHEN undefined_column THEN NULL;
        END;
        BEGIN
            EXECUTE 'ALTER TABLE floor_plans ALTER COLUMN markers SET DEFAULT ''[]''::jsonb';
        EXCEPTION
            WHEN undefined_column THEN NULL;
        END;

        -- Re-create FK to tours with correct types.
        BEGIN
            EXECUTE 'ALTER TABLE floor_plans ADD CONSTRAINT floor_plans_tour_id_fkey FOREIGN KEY (tour_id) REFERENCES tours(id) ON DELETE CASCADE';
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_floor_plans_tour_id ON floor_plans(tour_id);

-- Ensure the update_updated_at_column function exists (created in other migrations, but safe to re-define).
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

DROP TRIGGER IF EXISTS update_floor_plans_updated_at ON floor_plans;
CREATE TRIGGER update_floor_plans_updated_at
    BEFORE UPDATE ON floor_plans
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- =========================================================
-- 4) Media files table for uploads (used by /api/v1/upload/* endpoints)
-- =========================================================

CREATE TABLE IF NOT EXISTS media_files (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tour_id VARCHAR(36) REFERENCES tours(id) ON DELETE SET NULL,
    filename VARCHAR(255) NOT NULL,
    original_filename VARCHAR(255),
    file_url VARCHAR(512) NOT NULL,
    thumbnail_url VARCHAR(512),
    cdn_url VARCHAR(512),
    file_size BIGINT NOT NULL DEFAULT 0,
    mime_type VARCHAR(100) NOT NULL,
    width INTEGER,
    height INTEGER,
    duration INTEGER,
    folder VARCHAR(255),
    visibility VARCHAR(20) DEFAULT 'private',
    is_processed BOOLEAN DEFAULT FALSE,
    processing_metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    expires_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_media_files_user_id ON media_files(user_id);
CREATE INDEX IF NOT EXISTS idx_media_files_tour_id ON media_files(tour_id);
CREATE INDEX IF NOT EXISTS idx_media_files_mime_type ON media_files(mime_type);
CREATE INDEX IF NOT EXISTS idx_media_files_folder ON media_files(folder);
CREATE INDEX IF NOT EXISTS idx_media_files_visibility ON media_files(visibility);
CREATE INDEX IF NOT EXISTS idx_media_files_processed ON media_files(is_processed);
CREATE INDEX IF NOT EXISTS idx_media_files_created_at ON media_files(created_at);
CREATE INDEX IF NOT EXISTS idx_media_files_expires_at ON media_files(expires_at);

