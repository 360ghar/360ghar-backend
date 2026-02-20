-- Add retry_count column to ai_jobs table for tracking retry attempts
-- Migration: 20260124000100_add_ai_job_retry_count.sql

ALTER TABLE ai_jobs ADD COLUMN IF NOT EXISTS retry_count INTEGER DEFAULT 0;

-- Add comment for documentation
COMMENT ON COLUMN ai_jobs.retry_count IS 'Number of retry attempts for failed AI calls';
