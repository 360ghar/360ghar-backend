"""
AI Provider Factory and Exports.

This module provides the factory function for creating AI providers
and exports all necessary types for AI integration.

Providers are cached as singletons so the underlying httpx.AsyncClient
and connection pool are reused across calls instead of being leaked.

Usage:
    from app.services.ai import get_ai_provider, AIProviderType, AIMessage, VisionInput

    # Get a provider
    provider = get_ai_provider(AIProviderType.AGNES)

    # Use it
    response = await provider.complete(messages, vision_input)
"""

from enum import Enum

from app.config import settings
from app.core.constants import DEFAULT_VISION_PROVIDER
from app.core.logging import get_logger
from app.services.ai.base import (
    AIMessage,
    AIProvider,
    AIProviderConfig,
    AIProviderError,
    AIRole,
    VisionInput,
)

logger = get_logger(__name__)


class AIProviderType(str, Enum):
    """Supported AI provider types."""
    AGNES = "agnes"


# Singleton provider cache — one httpx client pool per provider type.
_provider_cache: dict[AIProviderType, AIProvider] = {}


def get_ai_provider(
    provider_type: AIProviderType = AIProviderType.AGNES,
    **config_overrides,
) -> AIProvider:
    """
    Get a cached AI provider instance (singleton per type).

    Reuses the same provider and httpx.AsyncClient across calls to avoid
    leaking connection pools.

    Args:
        provider_type: Provider type (only ``agnes`` is supported)
        **config_overrides: Override default configuration values (only used
            on first call; subsequent calls return the cached instance)

    Returns:
        AIProvider instance configured for the specified provider

    Raises:
        ValueError: If the API key is not configured
    """
    if provider_type in _provider_cache:
        if config_overrides:
            logger.warning(
                "AI provider %s already cached — config_overrides ignored",
                provider_type.value,
            )
        return _provider_cache[provider_type]

    if provider_type != AIProviderType.AGNES:
        raise ValueError(f"Unknown AI provider type: {provider_type}")

    from app.services.ai.providers.agnes import AgnesProvider

    api_key = settings.AGNES_AI_API_KEY
    if not api_key:
        raise ValueError("AGNES_AI_API_KEY not configured for Agnes AI provider")

    config = AIProviderConfig(
        api_key=api_key,
        model=config_overrides.pop("model", settings.AGNES_TEXT_MODEL),
        max_tokens=config_overrides.pop("max_tokens", 8000),
        temperature=config_overrides.pop("temperature", 0.7),
        timeout=config_overrides.pop("timeout", 120),
    )
    provider: AIProvider = AgnesProvider(config)

    _provider_cache[provider_type] = provider
    return provider


async def close_all_providers() -> None:
    """Close all cached provider HTTP clients. Call during app shutdown."""
    for p in _provider_cache.values():
        await p.close()
    _provider_cache.clear()
    from app.services.ai.nl_search import close_provider

    await close_provider()


def get_default_provider() -> AIProvider:
    """Return the Agnes AI provider (the only supported provider)."""
    return get_ai_provider(AIProviderType(DEFAULT_VISION_PROVIDER))


# Re-export commonly used types
__all__ = [
    "get_ai_provider",
    "get_default_provider",
    "AIProviderType",
    "AIProvider",
    "AIProviderConfig",
    "AIMessage",
    "AIRole",
    "VisionInput",
    "AIProviderError",
]
