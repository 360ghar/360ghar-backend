-- Blog post lifecycle: add status / scheduled_at / preview_token columns.
--
-- `status` (draft / published / archived / scheduled) replaces the boolean
-- `active` flag as the source of truth for visibility. `active` is retained
-- for backward compatibility and kept in sync (active = (status = 'published'))
-- by the service layer. Existing rows are backfilled from `active`.

-- 1. status column + backfill
ALTER TABLE public.blog_posts
  ADD COLUMN IF NOT EXISTS status varchar DEFAULT 'draft';

UPDATE public.blog_posts SET status = 'published' WHERE active = true;
UPDATE public.blog_posts SET status = 'draft' WHERE active = false OR active IS NULL;

CREATE INDEX IF NOT EXISTS idx_blog_posts_status ON public.blog_posts (status);

-- 2. scheduled_at column (for status = 'scheduled' auto-publish)
ALTER TABLE public.blog_posts
  ADD COLUMN IF NOT EXISTS scheduled_at timestamp with time zone;

-- 3. preview_token column + unique index (public draft preview sharing)
ALTER TABLE public.blog_posts
  ADD COLUMN IF NOT EXISTS preview_token varchar;

-- Unique constraint (partial: only enforces uniqueness for non-null tokens)
ALTER TABLE public.blog_posts
  DROP CONSTRAINT IF EXISTS blog_posts_preview_token_key;

ALTER TABLE public.blog_posts
  ADD CONSTRAINT blog_posts_preview_token_key UNIQUE (preview_token);

CREATE INDEX IF NOT EXISTS idx_blog_posts_preview_token
  ON public.blog_posts (preview_token)
  WHERE preview_token IS NOT NULL;
