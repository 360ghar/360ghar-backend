-- AI Jobs Migration
-- Creates table for AI processing jobs (scene analysis, hotspot suggestions, etc.)

-- AI Jobs table
CREATE TABLE IF NOT EXISTS ai_jobs (
    id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tour_id VARCHAR(36),
    scene_id VARCHAR(36),
    job_type VARCHAR(50) NOT NULL,
    status VARCHAR(20) DEFAULT 'pending' NOT NULL,
    progress INTEGER DEFAULT 0,
    result JSONB,
    error_message TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

-- Create indexes for ai_jobs
CREATE INDEX IF NOT EXISTS idx_ai_jobs_user_id ON ai_jobs(user_id);
CREATE INDEX IF NOT EXISTS idx_ai_jobs_status ON ai_jobs(status);
CREATE INDEX IF NOT EXISTS idx_ai_jobs_tour_id ON ai_jobs(tour_id) WHERE tour_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_ai_jobs_scene_id ON ai_jobs(scene_id) WHERE scene_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_ai_jobs_created_at ON ai_jobs(created_at);

-- Add trigger for updated_at
DROP TRIGGER IF EXISTS update_ai_jobs_updated_at ON ai_jobs;
CREATE TRIGGER update_ai_jobs_updated_at
    BEFORE UPDATE ON ai_jobs
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Add comments for documentation
COMMENT ON TABLE ai_jobs IS 'AI processing jobs for scene analysis, hotspot suggestions, and description generation';
COMMENT ON COLUMN ai_jobs.job_type IS 'Type of job: analyze_scene, analyze_scenes, suggest_hotspots, suggest_tour_hotspots, generate_description, generate_descriptions';
COMMENT ON COLUMN ai_jobs.status IS 'Job status: pending, processing, completed, failed, cancelled';
COMMENT ON COLUMN ai_jobs.progress IS 'Job progress percentage (0-100)';
COMMENT ON COLUMN ai_jobs.result IS 'JSON result containing analysis, suggestions, or descriptions';
