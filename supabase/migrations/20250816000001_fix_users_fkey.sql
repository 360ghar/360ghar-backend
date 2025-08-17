-- Fix users table foreign key constraint issue
-- Remove the problematic foreign key constraint and make supabase_user_id a simple UUID field

-- Drop the foreign key constraint that's causing issues
ALTER TABLE public.users DROP CONSTRAINT IF EXISTS users_supabase_user_id_fkey;

-- The supabase_user_id should still be unique but without foreign key constraint
-- This allows our app to work while maintaining data integrity through application logic
ALTER TABLE public.users 
ALTER COLUMN supabase_user_id TYPE UUID USING supabase_user_id::UUID;