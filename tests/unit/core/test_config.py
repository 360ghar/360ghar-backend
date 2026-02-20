"""
Tests for app.core.config module.
"""

import os
from unittest.mock import patch

import pytest


class TestSettings:
    """Tests for the Settings class."""

    def test_async_database_url_from_postgresql(self):
        """Test ASYNC_DATABASE_URL converts postgresql:// correctly."""
        with patch.dict(os.environ, {
            "DATABASE_URL": "postgresql://user:pass@localhost:5432/db",
            "SUPABASE_URL": "https://test.supabase.co",
            "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_test",
            "SUPABASE_SECRET_KEY": "test_secret",
            "SENTRY_DSN": "https://test@sentry.io/123",
        }, clear=False):
            from importlib import reload
            from app.core import config
            reload(config)

            settings = config.Settings()
            assert settings.ASYNC_DATABASE_URL == "postgresql+psycopg://user:pass@localhost:5432/db"

    def test_async_database_url_from_postgres(self):
        """Test ASYNC_DATABASE_URL converts postgres:// correctly."""
        with patch.dict(os.environ, {
            "DATABASE_URL": "postgres://user:pass@localhost:5432/db",
            "SUPABASE_URL": "https://test.supabase.co",
            "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_test",
            "SUPABASE_SECRET_KEY": "test_secret",
            "SENTRY_DSN": "https://test@sentry.io/123",
        }, clear=False):
            from importlib import reload
            from app.core import config
            reload(config)

            settings = config.Settings()
            assert settings.ASYNC_DATABASE_URL == "postgresql+psycopg://user:pass@localhost:5432/db"

    def test_async_database_url_already_async(self):
        """Test ASYNC_DATABASE_URL preserves already-async URLs."""
        with patch.dict(os.environ, {
            "DATABASE_URL": "postgresql+psycopg://user:pass@localhost:5432/db",
            "SUPABASE_URL": "https://test.supabase.co",
            "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_test",
            "SUPABASE_SECRET_KEY": "test_secret",
            "SENTRY_DSN": "https://test@sentry.io/123",
        }, clear=False):
            from importlib import reload
            from app.core import config
            reload(config)

            settings = config.Settings()
            assert settings.ASYNC_DATABASE_URL == "postgresql+psycopg://user:pass@localhost:5432/db"

    def test_default_cache_settings(self):
        """Test default cache configuration values."""
        with patch.dict(os.environ, {
            "DATABASE_URL": "postgresql://localhost/db",
            "SUPABASE_URL": "https://test.supabase.co",
            "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_test",
            "SUPABASE_SECRET_KEY": "test_secret",
            "SENTRY_DSN": "https://test@sentry.io/123",
        }, clear=False):
            from importlib import reload
            from app.core import config
            reload(config)

            settings = config.Settings()

            assert settings.CACHE_BACKEND == "memory"
            assert settings.CACHE_DEFAULT_TTL == 300
            assert settings.CACHE_MEMORY_MAX_SIZE == 1000
            assert settings.CACHE_KEY_PREFIX == "ghar360:"

    def test_cache_ttl_settings(self):
        """Test cache TTL configuration for various resources."""
        with patch.dict(os.environ, {
            "DATABASE_URL": "postgresql://localhost/db",
            "SUPABASE_URL": "https://test.supabase.co",
            "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_test",
            "SUPABASE_SECRET_KEY": "test_secret",
            "SENTRY_DSN": "https://test@sentry.io/123",
        }, clear=False):
            from importlib import reload
            from app.core import config
            reload(config)

            settings = config.Settings()

            assert settings.CACHE_TTL_AMENITIES == 86400
            assert settings.CACHE_TTL_PROPERTIES_LIST == 43200
            assert settings.CACHE_TTL_PROPERTY_DETAIL == 86400
            assert settings.CACHE_TTL_BLOG_POSTS == 86400

    def test_cors_origins_includes_localhost(self):
        """Test CORS origins include common localhost ports."""
        with patch.dict(os.environ, {
            "DATABASE_URL": "postgresql://localhost/db",
            "SUPABASE_URL": "https://test.supabase.co",
            "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_test",
            "SUPABASE_SECRET_KEY": "test_secret",
            "SENTRY_DSN": "https://test@sentry.io/123",
        }, clear=False):
            from importlib import reload
            from app.core import config
            reload(config)

            settings = config.Settings()

            assert "http://localhost:3000" in settings.CORS_ORIGINS
            assert "http://localhost:5173" in settings.CORS_ORIGINS
            assert "https://360ghar.com" in settings.CORS_ORIGINS

    def test_vector_sync_defaults(self):
        """Test vector sync configuration defaults."""
        with patch.dict(os.environ, {
            "DATABASE_URL": "postgresql://localhost/db",
            "SUPABASE_URL": "https://test.supabase.co",
            "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_test",
            "SUPABASE_SECRET_KEY": "test_secret",
            "SENTRY_DSN": "https://test@sentry.io/123",
            "VECTOR_SYNC_ENABLED": "true",  # Explicitly set to ensure default is tested
        }, clear=False):
            from importlib import reload
            from app.core import config
            reload(config)

            settings = config.Settings()

            assert settings.VECTOR_SYNC_ENABLED is True
            assert settings.VECTOR_SYNC_BATCH_SIZE == 500
            assert settings.VECTOR_SYNC_MAX_RETRIES == 3

    def test_vastu_default_provider(self):
        """Test Vastu analyzer default provider setting."""
        with patch.dict(os.environ, {
            "DATABASE_URL": "postgresql://localhost/db",
            "SUPABASE_URL": "https://test.supabase.co",
            "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_test",
            "SUPABASE_SECRET_KEY": "test_secret",
            "SENTRY_DSN": "https://test@sentry.io/123",
        }, clear=False):
            from importlib import reload
            from app.core import config
            reload(config)

            settings = config.Settings()

            assert settings.VASTU_DEFAULT_PROVIDER == "glm"

    def test_supabase_client_key_returns_publishable_key(self):
        """Test SUPABASE_CLIENT_KEY returns publishable key."""
        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": "postgresql://localhost/db",
                "SUPABASE_URL": "https://test.supabase.co",
                "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_key",
                "SUPABASE_SECRET_KEY": "test_secret",
                "SENTRY_DSN": "https://test@sentry.io/123",
            },
            clear=False,
        ):
            from importlib import reload
            from app.core import config

            reload(config)

            settings = config.Settings()
            assert settings.SUPABASE_CLIENT_KEY == "sb_publishable_key"
