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
    """
    Verify Supabase JWT token locally without a network call.
    This is much faster and more resilient than calling supabase.auth.get_user().
    """
    if not settings.SUPABASE_SECRET_KEY:
        logger.error("SUPABASE_SECRET_KEY is not set. Cannot verify token locally.")
        # Fallback or error, depending on security posture. For now, we'll fail closed.
        return None

    try:
        # Decode the token using the secret key and algorithm from settings
        payload = jwt.decode(
            token,
            settings.SUPABASE_SECRET_KEY,
            algorithms=[settings.ALGORITHM],
            audience="authenticated"  # Default Supabase audience
        )
        
        # The 'sub' claim in a Supabase JWT is the user's UUID.
        user_id = payload.get("sub")
        if user_id is None:
            logger.warning("Token payload is missing 'sub' (user ID) claim.")
            return None

        # Reconstruct a user-like object from the token payload
        # This should match the essential fields your app needs from the old get_user() call
        return {
            "id": user_id,
            "email": payload.get("email"),
            "user_metadata": payload.get("user_metadata", {}),
            "phone": payload.get("phone"),
            "email_verified": payload.get("email_confirmed_at") is not None,
            "role": payload.get("role"),
            "aud": payload.get("aud"),
            "exp": payload.get("exp"),
        }
    except JWTError as e:
        logger.warning(f"Local token verification failed: {e}")
        return None
    except Exception as e:
        logger.error(f"An unexpected error occurred during token verification: {e}")
        return None