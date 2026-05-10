"""Typed application settings.

This module is the canonical import location for configuration.
Import as: from app.config import settings  (or from app.config.settings import settings)
"""

from app.core.config import BASE_DIR, Settings, settings

__all__ = ["BASE_DIR", "Settings", "settings"]
