-- blog_posts.status had no NOT NULL and no CHECK. The ORM and BlogPostStatus allow
-- four values: draft, published, archived, scheduled.

-- A NULL status follows the active flag, as the service layer sets it.
UPDATE public.blog_posts
SET status = CASE WHEN active THEN 'published' ELSE 'draft' END
WHERE status IS NULL;

ALTER TABLE public.blog_posts ALTER COLUMN status SET NOT NULL;

-- NOT VALID: new and updated rows are checked. Existing rows are not scanned here.
-- Run VALIDATE CONSTRAINT blog_posts_status_check after the data is confirmed.
ALTER TABLE public.blog_posts
    ADD CONSTRAINT blog_posts_status_check
    CHECK (status IN ('draft', 'published', 'archived', 'scheduled')) NOT VALID;
