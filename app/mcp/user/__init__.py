"""
User MCP Server package.

Re-exports the user_mcp instance for backward compatibility.
Import as: from app.mcp.user import user_mcp
"""

from app.mcp.user.server import user_mcp

__all__ = ["user_mcp"]
