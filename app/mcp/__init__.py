"""
MCP (Model Context Protocol) servers for 360Ghar.

This module provides MCP server implementations for AI-powered integrations:

Servers:
    - user_mcp: User MCP server for owners, tenants, and regular users
    - admin_mcp: Admin MCP server for agents and administrators

URLs:
    - /mcp        -> user_mcp (primary endpoint for end-user applications)
    - /mcp-admin  -> admin_mcp (agent and admin tools)

Authentication:
    All servers use Supabase JWT authentication via OAuth 2.1 with PKCE.
    User roles are extracted from the token claims.
"""

from app.mcp.admin import admin_mcp
from app.mcp.auth_provider import SupabaseAuthProvider
from app.mcp.user import user_mcp

__all__ = [
    "user_mcp",
    "admin_mcp",
    "SupabaseAuthProvider",
]
