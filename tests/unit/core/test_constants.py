"""
Tests for app.core.constants module.
"""


class TestVisionConstants:
    """Tests for vision/AI provider constants."""

    def test_valid_vision_providers(self):
        from app.core.constants import VALID_VISION_PROVIDERS

        assert VALID_VISION_PROVIDERS == ("agnes",)

    def test_default_vision_provider_is_agnes(self):
        from app.core.constants import DEFAULT_VISION_PROVIDER

        assert DEFAULT_VISION_PROVIDER == "agnes"

    def test_default_vision_model_agnes(self):
        from app.core.constants import DEFAULT_VISION_MODEL_AGNES

        assert isinstance(DEFAULT_VISION_MODEL_AGNES, str)
        assert len(DEFAULT_VISION_MODEL_AGNES) > 0
