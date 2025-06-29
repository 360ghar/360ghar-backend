from supabase import create_client, Client
from app.core.config import settings

def get_supabase_client() -> Client:
    supabase: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
    return supabase

def get_supabase_admin_client() -> Client:
    supabase: Client = create_client(settings.SUPABASE_URL, settings.SUPABASE_SECRET_KEY)
    return supabase