from typing import Optional, Dict, Any
from supabase import Client
from app.core.config import settings
from app.core.supabase_client import get_supabase_client, get_supabase_admin_client
import jwt
import anyio
import logging

logger = logging.getLogger(__name__)

async def verify_supabase_token(token: str) -> Optional[Dict[str, Any]]:
    """Verify Supabase JWT token and return user data without blocking the event loop."""
    try:
        # Decode the JWT token header (no verification yet) for potential diagnostics
        _ = jwt.get_unverified_header(token)

        supabase = get_supabase_client()

        # Run blocking SDK call in a worker thread
        user_response = await anyio.to_thread.run_sync(lambda: supabase.auth.get_user(token))

        if getattr(user_response, "user", None):
            user = user_response.user
            return {
                "id": user.id,
                "email": user.email,
                "user_metadata": user.user_metadata,
                "app_metadata": user.app_metadata,
                "phone": user.phone,
                "email_verified": user.email_confirmed_at is not None,
                "phone_verified": user.phone_confirmed_at is not None,
            }
        return None
    except Exception as e:
        logger.error(f"Token verification error: {e}")
        return None

async def get_user_by_supabase_id(supabase_user_id: str) -> Optional[Dict[str, Any]]:
    """Get user from Supabase by user ID without blocking the event loop."""
    try:
        supabase = get_supabase_admin_client()
        user_response = await anyio.to_thread.run_sync(
            lambda: supabase.auth.admin.get_user_by_id(supabase_user_id)
        )

        if getattr(user_response, "user", None):
            user = user_response.user
            return {
                "id": user.id,
                "email": user.email,
                "user_metadata": user.user_metadata,
                "app_metadata": user.app_metadata,
                "phone": user.phone,
                "email_verified": user.email_confirmed_at is not None,
                "phone_verified": user.phone_confirmed_at is not None,
                "created_at": user.created_at,
                "updated_at": user.updated_at,
            }
        return None
    except Exception as e:
        logger.error(f"Error getting user by ID: {e}")
        return None