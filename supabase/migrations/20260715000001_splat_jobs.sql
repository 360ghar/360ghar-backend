-- =============================================================================
-- 3D Splat Lab – splat_jobs table
-- Migration: 20260715000001_splat_jobs.sql
--
-- Stores one record per Gaussian Splatting pipeline job.
-- Stages (status column):
--   pending → uploading → extracting → converting → sfm
--         → training → compressing → collision → ready
--   Any stage can transition to: failed
--
-- RLS: users can only read/modify their own rows.
-- GPU-gated stages: training / compressing / collision / ready require CUDA.
-- CPU-safe stages:  pending / uploading / extracting / converting / sfm.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- Table
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS splat_jobs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,

    -- Job metadata
    title               TEXT NOT NULL,

    -- Pipeline state
    status              TEXT NOT NULL DEFAULT 'pending'
                            CHECK (status IN (
                                'pending', 'uploading', 'extracting', 'converting',
                                'sfm', 'training', 'compressing', 'collision',
                                'ready', 'failed'
                            )),
    progress            SMALLINT NOT NULL DEFAULT 0
                            CHECK (progress BETWEEN 0 AND 100),
    stage_message       TEXT NOT NULL DEFAULT '',

    -- Job options
    is_360_video        BOOLEAN NOT NULL DEFAULT TRUE,
    mask_people         BOOLEAN NOT NULL DEFAULT FALSE,
    quality_preset      TEXT NOT NULL DEFAULT 'balanced'
                            CHECK (quality_preset IN ('fast', 'balanced', 'quality')),

    -- Storage references
    video_path          TEXT,           -- Supabase Storage path for source video
    splat_url           TEXT,           -- Public URL to final .spz Gaussian Splat file
    collision_url       TEXT,           -- Public URL to .collision.glb mesh
    supersplat_url      TEXT,           -- SuperSplat iframe share URL (if generated)

    -- Infrastructure
    daytona_sandbox_id  TEXT,           -- Daytona sandbox ID (cleared after job completes)
    error_message       TEXT,           -- Human-readable failure reason

    -- Audit
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_splat_jobs_user_id
    ON splat_jobs (user_id);

CREATE INDEX IF NOT EXISTS idx_splat_jobs_status
    ON splat_jobs (status);

CREATE INDEX IF NOT EXISTS idx_splat_jobs_user_created
    ON splat_jobs (user_id, created_at DESC);

-- ---------------------------------------------------------------------------
-- Auto-updated updated_at trigger (reuse existing helper if available)
-- ---------------------------------------------------------------------------

-- Create the trigger function only if it doesn't already exist from a prior migration.
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS set_splat_jobs_updated_at ON splat_jobs;
CREATE TRIGGER set_splat_jobs_updated_at
    BEFORE UPDATE ON splat_jobs
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ---------------------------------------------------------------------------
-- Row Level Security
-- ---------------------------------------------------------------------------

ALTER TABLE splat_jobs ENABLE ROW LEVEL SECURITY;

-- Users can view their own jobs
CREATE POLICY "splat_jobs_select_own"
    ON splat_jobs
    FOR SELECT
    USING (auth.uid() = user_id);

-- Users can create jobs for themselves only
CREATE POLICY "splat_jobs_insert_own"
    ON splat_jobs
    FOR INSERT
    WITH CHECK (auth.uid() = user_id);

-- Users can update their own jobs (e.g. cancel a pending job)
CREATE POLICY "splat_jobs_update_own"
    ON splat_jobs
    FOR UPDATE
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

-- Users can delete their own jobs
CREATE POLICY "splat_jobs_delete_own"
    ON splat_jobs
    FOR DELETE
    USING (auth.uid() = user_id);

-- Service role bypasses RLS (used by backend with SUPABASE_SECRET_KEY)
-- Supabase service role automatically bypasses RLS; no explicit policy needed.

-- ---------------------------------------------------------------------------
-- Comments
-- ---------------------------------------------------------------------------

COMMENT ON TABLE splat_jobs IS
    '3D Splat Lab: one row per Gaussian Splatting pipeline job. '
    'Status progresses through: pending → uploading → extracting → converting → sfm → training → compressing → collision → ready. '
    'CPU-safe up to sfm; training and beyond require CUDA GPU access on Daytona.';

COMMENT ON COLUMN splat_jobs.status IS
    'Pipeline stage. GPU required for: training, compressing, collision, ready.';
COMMENT ON COLUMN splat_jobs.progress IS
    'Integer 0-100 reflecting pipeline completion percentage.';
COMMENT ON COLUMN splat_jobs.daytona_sandbox_id IS
    'Active Daytona sandbox ID. Cleared after the sandbox is destroyed post-job.';
COMMENT ON COLUMN splat_jobs.video_path IS
    'Path inside the splat-jobs Supabase Storage bucket, e.g. <user_id>/<job_id>/video.mp4';
COMMENT ON COLUMN splat_jobs.splat_url IS
    'Public URL of the output .spz Gaussian Splat file once the job reaches ready status.';
COMMENT ON COLUMN splat_jobs.collision_url IS
    'Public URL of the .collision.glb mesh used for walkable collision detection.';
COMMENT ON COLUMN splat_jobs.supersplat_url IS
    'SuperSplat (superspl.at) iframe share URL if the splat was published there.';
