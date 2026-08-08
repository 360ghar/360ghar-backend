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
    media_file_id   VARCHAR(36) REFERENCES media_files(id) ON DELETE SET NULL,
    image_url       VARCHAR(500),
    frame_metadata  JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Logical frame identity: registration retries upsert on this key instead
    -- of creating duplicate frames (service add_frame ON CONFLICT DO UPDATE).
    CONSTRAINT uq_capture_frames_frame_identity
        UNIQUE (session_id, room_id, waypoint_id, frame_index)
);

CREATE INDEX IF NOT EXISTS idx_capture_frames_session_id
    ON capture_frames (session_id);

CREATE INDEX IF NOT EXISTS idx_capture_frames_session_room
    ON capture_frames (session_id, room_id);

-- ---------------------------------------------------------------------------
-- Row Level Security
--
-- capture_sessions.user_id is the local users.id (INTEGER), not the Supabase
-- auth uid, so ownership policies resolve the owner through users table.
-- public.users has RLS enabled with no policies, so the lookup must run in a
-- SECURITY DEFINER helper (same pattern as the flatmates realtime fix) that
-- still binds auth.uid() from the request JWT.
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.capture_session_owned_by(u_id INTEGER)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT EXISTS (
    SELECT 1
    FROM public.users u
    WHERE u.id = u_id
      AND u.supabase_user_id = (SELECT auth.uid())::text
  );
$$;

REVOKE ALL ON FUNCTION public.capture_session_owned_by(INTEGER) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.capture_session_owned_by(INTEGER) TO authenticated;

CREATE OR REPLACE FUNCTION public.capture_frame_owned_by(s_id VARCHAR)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT EXISTS (
    SELECT 1
    FROM public.capture_sessions s
    JOIN public.users u ON u.id = s.user_id
    WHERE s.id = s_id
      AND u.supabase_user_id = (SELECT auth.uid())::text
  );
$$;

REVOKE ALL ON FUNCTION public.capture_frame_owned_by(VARCHAR) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.capture_frame_owned_by(VARCHAR) TO authenticated;

ALTER TABLE capture_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE capture_frames ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "capture_sessions_select_own" ON capture_sessions;
CREATE POLICY "capture_sessions_select_own"
    ON capture_sessions
    FOR SELECT
    TO authenticated
    USING (public.capture_session_owned_by(user_id));

DROP POLICY IF EXISTS "capture_sessions_insert_own" ON capture_sessions;
CREATE POLICY "capture_sessions_insert_own"
    ON capture_sessions
    FOR INSERT
    TO authenticated
    WITH CHECK (public.capture_session_owned_by(user_id));

DROP POLICY IF EXISTS "capture_sessions_update_own" ON capture_sessions;
CREATE POLICY "capture_sessions_update_own"
    ON capture_sessions
    FOR UPDATE
    TO authenticated
    USING (public.capture_session_owned_by(user_id))
    WITH CHECK (public.capture_session_owned_by(user_id));

DROP POLICY IF EXISTS "capture_sessions_delete_own" ON capture_sessions;
CREATE POLICY "capture_sessions_delete_own"
    ON capture_sessions
    FOR DELETE
    TO authenticated
    USING (public.capture_session_owned_by(user_id));

DROP POLICY IF EXISTS "capture_frames_select_own" ON capture_frames;
CREATE POLICY "capture_frames_select_own"
    ON capture_frames
    FOR SELECT
    TO authenticated
    USING (public.capture_frame_owned_by(session_id));

DROP POLICY IF EXISTS "capture_frames_insert_own" ON capture_frames;
CREATE POLICY "capture_frames_insert_own"
    ON capture_frames
    FOR INSERT
    TO authenticated
    WITH CHECK (public.capture_frame_owned_by(session_id));

DROP POLICY IF EXISTS "capture_frames_update_own" ON capture_frames;
CREATE POLICY "capture_frames_update_own"
    ON capture_frames
    FOR UPDATE
    TO authenticated
    USING (public.capture_frame_owned_by(session_id))
    WITH CHECK (public.capture_frame_owned_by(session_id));

DROP POLICY IF EXISTS "capture_frames_delete_own" ON capture_frames;
CREATE POLICY "capture_frames_delete_own"
    ON capture_frames
    FOR DELETE
    TO authenticated
    USING (public.capture_frame_owned_by(session_id));

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
