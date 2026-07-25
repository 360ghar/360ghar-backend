-- =============================================================================
-- Guided capture sessions (mobile capture app)
-- Migration: 20260722000001_capture_sessions.sql
--
-- Phase 0 tables for CaptureSession + CaptureFrame.
-- Tour promotion / stitch processing arrives in later phases.
-- =============================================================================

DO $$ BEGIN
    CREATE TYPE capture_session_status AS ENUM (
        'draft',
        'capturing',
        'review',
        'uploading',
        'processing',
        'ready',
        'failed',
        'cancelled'
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS capture_sessions (
    id              VARCHAR(36) PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title           VARCHAR(255) NOT NULL,
    description     TEXT,
    status          capture_session_status NOT NULL DEFAULT 'draft',
    progress        INTEGER NOT NULL DEFAULT 0,
    plan            JSONB,
    device_info     JSONB,
    tour_id         VARCHAR(36) REFERENCES tours(id) ON DELETE SET NULL,
    error_message   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT capture_sessions_progress_range CHECK (progress BETWEEN 0 AND 100)
);

CREATE INDEX IF NOT EXISTS idx_capture_sessions_user_id
    ON capture_sessions (user_id);

CREATE INDEX IF NOT EXISTS idx_capture_sessions_status
    ON capture_sessions (status);

CREATE INDEX IF NOT EXISTS idx_capture_sessions_user_created
    ON capture_sessions (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS capture_frames (
    id              VARCHAR(36) PRIMARY KEY,
    session_id      VARCHAR(36) NOT NULL REFERENCES capture_sessions(id) ON DELETE CASCADE,
    room_id         VARCHAR(64) NOT NULL,
    room_label      VARCHAR(255),
    waypoint_id     VARCHAR(64) NOT NULL,
    waypoint_index  INTEGER NOT NULL DEFAULT 0,
    frame_index     INTEGER NOT NULL DEFAULT 0,
    media_file_id   VARCHAR(36),
    image_url       VARCHAR(500),
    frame_metadata  JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_capture_frames_session_id
    ON capture_frames (session_id);

CREATE INDEX IF NOT EXISTS idx_capture_frames_session_room
    ON capture_frames (session_id, room_id);

-- updated_at trigger (reuse helper if present)
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_capture_sessions_updated_at ON capture_sessions;
CREATE TRIGGER trg_capture_sessions_updated_at
    BEFORE UPDATE ON capture_sessions
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
