-- Add termination_date and termination_reason columns to leases

ALTER TABLE public.leases
    ADD COLUMN IF NOT EXISTS termination_date date,
    ADD COLUMN IF NOT EXISTS termination_reason text;