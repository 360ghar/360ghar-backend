"""
Visits tools registration for User MCP Server.

Imports the ChatGPT visit tools module to register visits_*
tools on the user_mcp server instance. The actual tool implementations
live in app.mcp.chatgpt.visit_tools.
"""

from __future__ import annotations

from app.core.logging import get_logger

# Import the user MCP server instance (needed for the chatgpt tools to register on)
from app.mcp.user.server import user_mcp  # noqa: F401

logger = get_logger(__name__)

# Import ChatGPT visit tools to register them on the user_mcp server
try:
    from app.mcp.chatgpt import visit_tools  # noqa: F401
except ImportError as e:
    logger.warning("ChatGPT visit tools not registered: %s", e)
