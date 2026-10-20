-- Flatmates chat delivers messages through Realtime broadcast from the backend.
-- Clients must not read public.messages through PostgREST. With RLS on and no
-- policy, anon and authenticated roles read no rows. The backend connects as the
-- table owner, which is not affected.
--
-- Both chat clients (360-flatmates Flutter app and 360-flatmates-web) read chat only
-- through the backend API and Realtime broadcast. Neither calls .from('messages').

ALTER TABLE public.messages ENABLE ROW LEVEL SECURITY;
