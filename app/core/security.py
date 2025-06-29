from typing import Optional, Dict, Any
from supabase import Client
from app.core.config import settings
from app.core.supabase_client import get_supabase_client, get_supabase_admin_client
import jwt

def verify_supabase_token(token: str) -> Optional[Dict[str, Any]]:
    """Verify Supabase JWT token and return user data"""
    try:
        # Decode the JWT token without verification first to get the header
        unverified_header = jwt.get_unverified_header(token)
        
        # Get the Supabase client for verification
        supabase = get_supabase_client()
        
        # Verify the token with Supabase
        user_response = supabase.auth.get_user(token)
        
        if user_response.user:
            return {
                "id": user_response.user.id,
                "email": user_response.user.email,
                "user_metadata": user_response.user.user_metadata,
                "app_metadata": user_response.user.app_metadata,
                "phone": user_response.user.phone,
                "email_verified": user_response.user.email_confirmed_at is not None,
                "phone_verified": user_response.user.phone_confirmed_at is not None
            }
        return None
    except Exception as e:
        print(f"Token verification error: {e}")
        return None

def get_user_by_supabase_id(supabase_user_id: str) -> Optional[Dict[str, Any]]:
    """Get user from Supabase by user ID"""
    try:
        supabase = get_supabase_admin_client()
        user_response = supabase.auth.admin.get_user_by_id(supabase_user_id)
        
        if user_response.user:
            return {
                "id": user_response.user.id,
                "email": user_response.user.email,
                "user_metadata": user_response.user.user_metadata,
                "app_metadata": user_response.user.app_metadata,
                "phone": user_response.user.phone,
                "email_verified": user_response.user.email_confirmed_at is not None,
                "phone_verified": user_response.user.phone_confirmed_at is not None,
                "created_at": user_response.user.created_at,
                "updated_at": user_response.user.updated_at
            }
        return None
    except Exception as e:
        print(f"Error getting user by ID: {e}")
        return None