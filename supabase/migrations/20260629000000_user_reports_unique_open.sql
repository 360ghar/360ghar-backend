-- Migration to add partial unique index to user_reports to prevent race conditions

-- First, backfill/cleanup legacy duplicate open reports
-- Keep only the oldest open report for each (reporter, reported) pair,
-- and set the rest to 'resolved'.
UPDATE user_reports
SET status = 'resolved'
WHERE id IN (
    SELECT id
    FROM (
        SELECT id,
               ROW_NUMBER() OVER (PARTITION BY reporter_user_id, reported_user_id ORDER BY created_at ASC) as rn
        FROM user_reports
        WHERE status = 'open'
    ) sub
    WHERE sub.rn > 1
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_user_reports_unique_open 
ON user_reports (reporter_user_id, reported_user_id) 
WHERE status = 'open';
