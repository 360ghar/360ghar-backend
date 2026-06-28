"""Auth service package.

Holds backend-side auth helpers that complement Supabase GoTrue (session
revocation, identity linking, etc.).
"""

from .session_revocation import revoke_all_user_sessions

__all__ = ["revoke_all_user_sessions"]
