-- The ORM declares these columns NOT NULL. The data hub and blog migrations left them
-- nullable, each with a DEFAULT. The app always writes a value, so NULL rows are not
-- expected. Backfill any NULL with the column default, then set NOT NULL.
-- Not applied to any database. The integrator applies it after owner approval.

-- Blog timestamps (the ORM default is now()).
UPDATE public.blog_categories SET created_at = NOW() WHERE created_at IS NULL;
ALTER TABLE public.blog_categories ALTER COLUMN created_at SET NOT NULL;

UPDATE public.blog_tags SET created_at = NOW() WHERE created_at IS NULL;
ALTER TABLE public.blog_tags ALTER COLUMN created_at SET NOT NULL;

UPDATE public.blog_post_categories SET created_at = NOW() WHERE created_at IS NULL;
ALTER TABLE public.blog_post_categories ALTER COLUMN created_at SET NOT NULL;

UPDATE public.blog_post_tags SET created_at = NOW() WHERE created_at IS NULL;
ALTER TABLE public.blog_post_tags ALTER COLUMN created_at SET NOT NULL;

UPDATE public.blog_posts SET created_at = NOW() WHERE created_at IS NULL;
ALTER TABLE public.blog_posts ALTER COLUMN created_at SET NOT NULL;

-- Auction and alert flags (the ORM default is true).
UPDATE public.bank_auctions SET is_active = TRUE WHERE is_active IS NULL;
ALTER TABLE public.bank_auctions ALTER COLUMN is_active SET NOT NULL;

UPDATE public.court_auctions SET is_active = TRUE WHERE is_active IS NULL;
ALTER TABLE public.court_auctions ALTER COLUMN is_active SET NOT NULL;

UPDATE public.auction_alerts SET is_active = TRUE WHERE is_active IS NULL;
ALTER TABLE public.auction_alerts ALTER COLUMN is_active SET NOT NULL;

-- Counters (the ORM default is 0).
UPDATE public.rera_projects SET complaint_count = 0 WHERE complaint_count IS NULL;
ALTER TABLE public.rera_projects ALTER COLUMN complaint_count SET NOT NULL;

UPDATE public.neighbourhood_scores SET api_calls_made = 0 WHERE api_calls_made IS NULL;
ALTER TABLE public.neighbourhood_scores ALTER COLUMN api_calls_made SET NOT NULL;

-- Scraper run columns (the ORM defaults are 'cron' and 0).
UPDATE public.scraper_runs SET run_type = 'cron' WHERE run_type IS NULL;
ALTER TABLE public.scraper_runs ALTER COLUMN run_type SET NOT NULL;

UPDATE public.scraper_runs SET records_found = 0 WHERE records_found IS NULL;
ALTER TABLE public.scraper_runs ALTER COLUMN records_found SET NOT NULL;

UPDATE public.scraper_runs SET records_upserted = 0 WHERE records_upserted IS NULL;
ALTER TABLE public.scraper_runs ALTER COLUMN records_upserted SET NOT NULL;

UPDATE public.scraper_runs SET records_failed = 0 WHERE records_failed IS NULL;
ALTER TABLE public.scraper_runs ALTER COLUMN records_failed SET NOT NULL;
