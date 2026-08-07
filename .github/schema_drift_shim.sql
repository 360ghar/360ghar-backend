-- Supabase-compat shims so supabase/migrations/*.sql can be applied to a
-- plain Postgres (used by the CI schema-drift job; the migrations reference
-- Supabase platform objects):
--   * auth.users FKs (notifications, splat_jobs)
--   * auth.uid() in RLS policies (flatmates realtime, splat_jobs)
--   * the `authenticated` role for GRANT/POLICY statements
--   * storage.buckets seeding (vector_and_storage migration)
--   * realtime.messages + realtime.topic() for private-broadcast policies
--
-- These are minimal stand-ins so the migration tree applies cleanly; they
-- are not used at runtime and do not affect production.

DO $$ BEGIN CREATE ROLE anon NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE authenticated NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE service_role NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE SCHEMA IF NOT EXISTS auth;
CREATE TABLE IF NOT EXISTS auth.users (id uuid PRIMARY KEY);
CREATE OR REPLACE FUNCTION auth.uid() RETURNS uuid
LANGUAGE sql STABLE AS $$ SELECT NULL::uuid $$;

CREATE SCHEMA IF NOT EXISTS storage;
CREATE TABLE IF NOT EXISTS storage.buckets (
    id text PRIMARY KEY,
    name text NOT NULL,
    public boolean DEFAULT false,
    file_size_limit bigint,
    allowed_mime_types text[]
);

CREATE SCHEMA IF NOT EXISTS realtime;
CREATE TABLE IF NOT EXISTS realtime.messages (
    topic text,
    extension text
);
CREATE OR REPLACE FUNCTION realtime.topic() RETURNS text
LANGUAGE sql STABLE AS $$ SELECT NULL::text $$;
