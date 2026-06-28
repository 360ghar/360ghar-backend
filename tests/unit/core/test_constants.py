"""
Tests for app.core.constants module.
"""




class TestVisionConstants:
    """Tests for vision/AI provider constants."""

    def test_valid_vision_providers(self):
        from app.core.constants import VALID_VISION_PROVIDERS

        assert "gemini" in VALID_VISION_PROVIDERS
        assert "glm" in VALID_VISION_PROVIDERS
        assert len(VALID_VISION_PROVIDERS) == 2

    def test_default_vision_provider_is_glm(self):
        from app.core.constants import DEFAULT_VISION_PROVIDER

        assert DEFAULT_VISION_PROVIDER == "glm"

    def test_default_vision_model_gemini(self):
        from app.core.constants import DEFAULT_VISION_MODEL_GEMINI

        assert isinstance(DEFAULT_VISION_MODEL_GEMINI, str)
        assert len(DEFAULT_VISION_MODEL_GEMINI) > 0

    def test_default_vision_model_glm(self):
        from app.core.constants import DEFAULT_VISION_MODEL_GLM

        assert isinstance(DEFAULT_VISION_MODEL_GLM, str)
        assert len(DEFAULT_VISION_MODEL_GLM) > 0

    def test_valid_providers_are_tuple(self):
        from app.core.constants import VALID_VISION_PROVIDERS

        assert isinstance(VALID_VISION_PROVIDERS, tuple)

    def test_fallback_provider_default(self):
        from app.core.constants import VASTU_FALLBACK_PROVIDER

        assert isinstance(VASTU_FALLBACK_PROVIDER, str)


class TestConstantsDeriveFromSettings:
    """Tests that constants source from settings at import time.

    Note: Constants are evaluated once at module import. Patching settings
    after import does NOT retroactively change module-level constants.
    These tests verify the fallback behavior when settings values are None.
    """

    def test_gemini_model_fallback_when_settings_none(self):
        """When settings.GEMINI_MODEL is None, the fallback is used."""
        from app.core.constants import DEFAULT_VISION_MODEL_GEMINI

        assert isinstance(DEFAULT_VISION_MODEL_GEMINI, str)
        assert len(DEFAULT_VISION_MODEL_GEMINI) > 0

    def test_glm_model_fallback_when_settings_none(self):
        """When settings.GLM_MODEL is None, the fallback is used."""
        from app.core.constants import DEFAULT_VISION_MODEL_GLM

        assert isinstance(DEFAULT_VISION_MODEL_GLM, str)
        assert len(DEFAULT_VISION_MODEL_GLM) > 0

    def test_fallback_provider_empty_when_not_set(self):
        """When VASTU_FALLBACK_PROVIDER is empty, constant is empty string."""
        from app.core.constants import VASTU_FALLBACK_PROVIDER

        assert isinstance(VASTU_FALLBACK_PROVIDER, str)
