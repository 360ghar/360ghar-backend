-- Migration to add partial unique index to user_reports to prevent race conditions

CREATE UNIQUE INDEX IF NOT EXISTS idx_user_reports_unique_open 
ON user_reports (reporter_user_id, reported_user_id) 
WHERE status = 'open';
