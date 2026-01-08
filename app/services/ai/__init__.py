"""
AI Provider Factory and Exports.

This module provides the factory function for creating AI providers
and exports all necessary types for AI integration.

Usage:
    from app.services.ai import get_ai_provider, AIProviderType, AIMessage, VisionInput

    # Get a provider
    provider = get_ai_provider(AIProviderType.GEMINI)

    # Use it
    response = await provider.complete(messages, vision_input)
"""

from enum import Enum
from typing import Optional

from app.core.config import settings
from app.services.ai.base import (
    AIProvider,
    AIProviderConfig,
    AIMessage,
    AIRole,
    VisionInput,
    AIProviderError,
)


class AIProviderType(str, Enum):
    """Supported AI provider types."""
    GEMINI = "gemini"
    GLM = "glm"


def get_ai_provider(
    provider_type: AIProviderType = AIProviderType.GEMINI,
    **config_overrides,
) -> AIProvider:
    """
    Factory function to get an AI provider instance.

    Args:
        provider_type: Type of provider to create (gemini, glm)
        **config_overrides: Override default configuration values

    Returns:
        AIProvider instance configured for the specified provider

    Raises:
        ValueError: If provider type is unknown or API key is not configured

    Example:
        # Get Gemini provider with default settings
        provider = get_ai_provider(AIProviderType.GEMINI)

        # Get GLM provider with custom temperature
        provider = get_ai_provider(AIProviderType.GLM, temperature=0.5)
    """
    if provider_type == AIProviderType.GEMINI:
        from app.services.ai.providers.gemini import GeminiProvider

        api_key = settings.GOOGLE_API_KEY
        if not api_key:
            raise ValueError("GOOGLE_API_KEY not configured for Gemini provider")

        config = AIProviderConfig(
            api_key=api_key,
            model=config_overrides.pop("model", settings.GEMINI_MODEL),
            max_tokens=config_overrides.pop("max_tokens", 8000),
            temperature=config_overrides.pop("temperature", 0.7),
            timeout=config_overrides.pop("timeout", 120),
        )
        return GeminiProvider(config)

    elif provider_type == AIProviderType.GLM:
        from app.services.ai.providers.glm import GLMProvider

        api_key = getattr(settings, "GLM_API_KEY", None)
        if not api_key:
            raise ValueError("GLM_API_KEY not configured for GLM provider")

        config = AIProviderConfig(
            api_key=api_key,
            model=config_overrides.pop("model", getattr(settings, "GLM_MODEL", "glm-4.6v-flash")),
            max_tokens=config_overrides.pop("max_tokens", 4000),
            temperature=config_overrides.pop("temperature", 0.7),
            timeout=config_overrides.pop("timeout", 120),
        )
        return GLMProvider(config)

    else:
        raise ValueError(f"Unknown AI provider type: {provider_type}")


def get_default_provider() -> AIProvider:
    """
    Get the default AI provider based on configuration.

    Falls back to Gemini if no preference is set.
    """
    default_type = getattr(settings, "VASTU_DEFAULT_PROVIDER", "gemini")
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
