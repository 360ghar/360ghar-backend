-- ============================================================
-- Watchlist: store the alert baseline on its own column.
-- ============================================================
-- The alert service compared current project values with the watch's
-- updated_at. Any edit to the watch (notes, alert switches) moved that time,
-- so a change that happened before the edit was never alerted. The service
-- now stores the values it last reported in alert_baseline. The watchlist
-- service seeds it when a watch is created, and the alert service moves it
-- after each run; user edits never change it.
--
-- Additive. Existing rows get NULL; the next alert run fills the baseline
-- from the current values and sends nothing for that row.
-- ============================================================

ALTER TABLE project_watchlist ADD COLUMN IF NOT EXISTS alert_baseline JSONB;
