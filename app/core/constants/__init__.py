"""
Application-wide constants.

Values are sourced from settings (env vars) with hardcoded fallbacks so that
a single source of truth is available for models, providers, and other defaults
that must not drift across modules.
"""

from app.config import settings

# Valid vision provider identifiers
VALID_VISION_PROVIDERS: tuple[str, ...] = ("agnes",)


def __getattr__(name: str):
    """Lazily resolve constants from settings to avoid stale import-time values."""
    _LAZY_CONSTANTS = {
        "DEFAULT_VISION_MODEL_AGNES": lambda: settings.AGNES_TEXT_MODEL or "agnes-3.0-flash",
        "DEFAULT_VISION_PROVIDER": lambda: "agnes",
    }
    if name in _LAZY_CONSTANTS:
        return _LAZY_CONSTANTS[name]()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
