-- Drop the enum type message_thread_type. The migration 20260621000001 created it
-- with lease, maintenance and general, but no table column uses it and no Python
-- enum mirrors it. Nothing depends on it, so DROP TYPE does not cascade.

DROP TYPE IF EXISTS message_thread_type;
