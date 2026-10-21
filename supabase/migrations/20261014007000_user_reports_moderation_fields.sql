-- Split moderator output from the reporter's text on user_reports.
-- Before: moderate_report wrote the moderator note into `notes`, which overwrote
-- the reporter's description. After: `notes` keeps the reporter's text only.

ALTER TABLE public.user_reports
    ADD COLUMN IF NOT EXISTS moderator_notes TEXT,
    ADD COLUMN IF NOT EXISTS moderated_by BIGINT REFERENCES public.users (id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS moderated_at TIMESTAMPTZ;
