"""
Discovery tools registration for User MCP Server.

Imports the ChatGPT discovery tools module to register discovery_*
tools on the user_mcp server instance. The actual tool implementations
live in app.mcp.chatgpt.discovery_tools.
"""

from __future__ import annotations

from app.core.logging import get_logger

# Import the user MCP server instance (needed for the chatgpt tools to register on)
from app.mcp.user.server import user_mcp  # noqa: F401

logger = get_logger(__name__)

# Import ChatGPT discovery tools to register them on the user_mcp server
try:
    from app.mcp.chatgpt import discovery_tools  # noqa: F401
except ImportError as e:
    logger.warning("ChatGPT discovery tools not registered: %s", e)
