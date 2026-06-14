-- Migration: Add onboarding completion columns for stays, estate, and ghar360 apps.
-- These columns drive the APP_ONBOARDING gate in the auth state-machine.
-- The flatmates_onboarding_completed column already exists (added in
-- 20260423000000_create_flatmates_social_primitives.sql).

ALTER TABLE public.users
  ADD COLUMN IF NOT EXISTS stays_onboarding_completed boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS estate_onboarding_completed boolean NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS ghar360_onboarding_completed boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN public.users.stays_onboarding_completed IS 'Whether the user has completed the stays app onboarding flow';
COMMENT ON COLUMN public.users.estate_onboarding_completed IS 'Whether the user has completed the estate app onboarding flow';
COMMENT ON COLUMN public.users.ghar360_onboarding_completed IS 'Whether the user has completed the ghar360 app onboarding flow';
