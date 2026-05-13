-- Blog SEO enhancement: add structured SEO, sourcing, and analytics fields to blog_posts
-- Enables: meta tags, structured data, source tracking, reading analytics, and flexible SEO metadata

-- SEO fields
ALTER TABLE public.blog_posts
  ADD COLUMN IF NOT EXISTS meta_title varchar(60),
  ADD COLUMN IF NOT EXISTS meta_description varchar(160),
  ADD COLUMN IF NOT EXISTS focus_keyword varchar(200),
  ADD COLUMN IF NOT EXISTS canonical_url varchar(500),
  ADD COLUMN IF NOT EXISTS og_image_url varchar(500);

-- Reading analytics
ALTER TABLE public.blog_posts
  ADD COLUMN IF NOT EXISTS reading_time_minutes integer,
  ADD COLUMN IF NOT EXISTS word_count integer;

-- Publishing timestamp (separate from created_at for scheduling)
ALTER TABLE public.blog_posts
  ADD COLUMN IF NOT EXISTS published_at timestamp with time zone;

-- Structured sources: JSONB array of {url, name, type, retrieved_at}
ALTER TABLE public.blog_posts
  ADD COLUMN IF NOT EXISTS sources jsonb NOT NULL DEFAULT '[]'::jsonb;

-- Flexible SEO metadata: schema_markup (JSON-LD), keyword_analysis, trending_score, etc.
ALTER TABLE public.blog_posts
  ADD COLUMN IF NOT EXISTS seo_metadata jsonb NOT NULL DEFAULT '{}'::jsonb;

-- Indexes for SEO lookups and analytics
CREATE INDEX IF NOT EXISTS ix_blog_posts_focus_keyword ON public.blog_posts (focus_keyword);
CREATE INDEX IF NOT EXISTS ix_blog_posts_published_at ON public.blog_posts (published_at);
CREATE INDEX IF NOT EXISTS ix_blog_posts_seo_metadata ON public.blog_posts USING gin (seo_metadata);
