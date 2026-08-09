"""
AI Provider Factory and Exports.

This module provides the factory function for creating AI providers
and exports all necessary types for AI integration.

Providers are cached as singletons so the underlying httpx.AsyncClient
and connection pool are reused across calls instead of being leaked.

Usage:
    from app.services.ai import get_ai_provider, AIProviderType, AIMessage, VisionInput

    # Get a provider
    provider = get_ai_provider(AIProviderType.GEMINI)

    # Use it
    response = await provider.complete(messages, vision_input)
"""

from enum import Enum

from app.config import settings
from app.core.constants import (
    DEFAULT_VISION_MODEL_GEMINI,
    DEFAULT_VISION_MODEL_GLM,
    DEFAULT_VISION_PROVIDER,
)
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
    GEMINI = "gemini"
    OPENAI = "openai"
    GLM = "glm"


# Singleton provider cache — one httpx client pool per provider type.
_provider_cache: dict[AIProviderType, AIProvider] = {}


def get_ai_provider(
    provider_type: AIProviderType = AIProviderType.GEMINI,
    **config_overrides,
) -> AIProvider:
    """
    Get a cached AI provider instance (singleton per type).

    Reuses the same provider and httpx.AsyncClient across calls to avoid
    leaking connection pools.

    Args:
        provider_type: Type of provider to create (gemini, openai)
        **config_overrides: Override default configuration values (only used
            on first call; subsequent calls return the cached instance)

    Returns:
        AIProvider instance configured for the specified provider

    Raises:
        ValueError: If provider type is unknown or API key is not configured
    """
    if provider_type in _provider_cache:
        if config_overrides:
            logger.warning(
                "AI provider %s already cached — config_overrides ignored",
                provider_type.value,
            )
        return _provider_cache[provider_type]

    if provider_type == AIProviderType.GEMINI:
        from app.services.ai.providers.gemini import GeminiProvider

        api_key = settings.GOOGLE_API_KEY
        if not api_key:
            raise ValueError("GOOGLE_API_KEY not configured for Gemini provider")

        config = AIProviderConfig(
            api_key=api_key,
            model=config_overrides.pop("model", DEFAULT_VISION_MODEL_GEMINI),
            max_tokens=config_overrides.pop("max_tokens", 24000),
            temperature=config_overrides.pop("temperature", 0.7),
            timeout=config_overrides.pop("timeout", 120),
        )
        provider: AIProvider = GeminiProvider(config)

    elif provider_type == AIProviderType.OPENAI:
        from app.services.ai.providers.openai import OpenAIProvider

        api_key = getattr(settings, "CUSTOM_OPENAI_API_KEY", None)
        if not api_key:
            raise ValueError("CUSTOM_OPENAI_API_KEY not configured for OpenAI provider")

        config = AIProviderConfig(
            api_key=api_key,
            model=config_overrides.pop("model", getattr(settings, "CUSTOM_OPENAI_DEFAULT_MODEL", "gpt-4o-mini")),
            max_tokens=config_overrides.pop("max_tokens", 4000),
            temperature=config_overrides.pop("temperature", 0.7),
            timeout=config_overrides.pop("timeout", 120),
        )
        provider = OpenAIProvider(config)

    elif provider_type == AIProviderType.GLM:
        from app.services.ai.providers.glm import GLMProvider

        api_key = getattr(settings, "GLM_API_KEY", None)
        if not api_key:
            raise ValueError("GLM_API_KEY not configured for GLM provider")

        config = AIProviderConfig(
            api_key=api_key,
            model=config_overrides.pop("model", DEFAULT_VISION_MODEL_GLM),
            max_tokens=config_overrides.pop("max_tokens", 4000),
            temperature=config_overrides.pop("temperature", 0.7),
            timeout=config_overrides.pop("timeout", 120),
        )
        provider = GLMProvider(config)

    else:
        raise ValueError(f"Unknown AI provider type: {provider_type}")

    _provider_cache[provider_type] = provider
    return provider


async def close_all_providers() -> None:
    """Close all cached provider HTTP clients. Call during app shutdown."""
    for p in _provider_cache.values():
        await p.close()
    _provider_cache.clear()


def get_default_provider() -> AIProvider:
    """
    Get the default AI provider based on configuration.

    Falls back to Gemini if no preference is set.
    """
    default_type = DEFAULT_VISION_PROVIDER
    try:
        provider_type = AIProviderType(default_type.lower())
    except ValueError:
        provider_type = AIProviderType.GEMINI
    return get_ai_provider(provider_type)


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
