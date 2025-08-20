import anyio
from supabase import create_client, Client
from jose import jwt, JWTError
from app.core.config import settings
from typing import Optional, Dict, Any
from app.core.logging import get_logger

logger = get_logger(__name__)

# Supabase client for auth only
_supabase_client: Client = None

def get_supabase_auth_client() -> Client:
    """Get Supabase client for authentication only"""
    global _supabase_client
    if _supabase_client is None:
        _supabase_client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
    return _supabase_client

async def verify_supabase_token(token: str) -> Optional[Dict[str, Any]]:
    """Verify Supabase JWT token"""
    try:
        supabase = get_supabase_auth_client()
        user_response = await anyio.to_thread.run_sync(
            lambda: supabase.auth.get_user(token)
        )
        if user_response.user:
            return {
                "id": user_response.user.id,
                "email": user_response.user.email,
                "user_metadata": user_response.user.user_metadata,
                "phone": user_response.user.phone,
                "email_verified": user_response.user.email_confirmed_at is not None
            }
        return None
    except Exception as e:
        logger.error(f"Error verifying Supabase token: {e}")
        return None
