"""
Tests for app.core.config module.
"""

import os
from unittest.mock import patch


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

            assert settings.CACHE_BACKEND == "disk"
            assert settings.CACHE_DEFAULT_TTL == 300
            assert settings.CACHE_MEMORY_MAX_SIZE == 1000
            assert settings.CACHE_MEMORY_MAX_ENTRY_BYTES == 1_000_000
            assert settings.CACHE_DISK_DIR == "./cache"
            assert settings.CACHE_DISK_MAX_SIZE == 1000
            assert settings.CACHE_DISK_MAX_ENTRY_BYTES == 1_000_000
            assert settings.CACHE_REDIS_MAX_CONNECTIONS == 15
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
            assert settings.CACHE_TTL_VERSIONS == 3600

    def test_default_database_pool_settings_are_session_pooler_safe(self):
        """Default non-serverless pool capacity must stay below Supabase's small session cap."""
        from app.core.config import Settings

        assert Settings.model_fields["DB_POOL_SIZE"].default == 4
        assert Settings.model_fields["DB_MAX_OVERFLOW"].default == 0
        assert Settings.model_fields["DB_BG_POOL_SIZE"].default == 1
        assert Settings.model_fields["DB_BG_MAX_OVERFLOW"].default == 0

    def test_secret_fields_remain_plain_string_attributes(self):
        """Secret config values stay usable as raw strings on Settings attributes."""
        from app.core.config import Settings

        settings = Settings(
            DATABASE_URL="postgresql://user:password@localhost/db",
            SUPABASE_URL="https://test.supabase.co",
            SUPABASE_PUBLISHABLE_KEY="sb_publishable_test",
            SUPABASE_SECRET_KEY="supabase-secret",
            SECRET_KEY="jwt-secret",
        )

        assert settings.SECRET_KEY == "jwt-secret"
        assert settings.SUPABASE_SECRET_KEY == "supabase-secret"
        assert settings.DATABASE_URL == "postgresql://user:password@localhost/db"
        assert isinstance(settings.SECRET_KEY, str)
        assert isinstance(settings.SUPABASE_SECRET_KEY, str)
        assert isinstance(settings.DATABASE_URL, str)

    def test_repr_and_default_dump_redact_secret_fields(self):
        """Common debug representations must not leak configured secrets."""
        from app.core.config import Settings

        settings = Settings(
            DATABASE_URL="postgresql://user:password@localhost/db",
            REDIS_URL="redis://:redis-password@localhost:6379",
            SUPABASE_URL="https://test.supabase.co",
            SUPABASE_PUBLISHABLE_KEY="sb_publishable_test",
            SUPABASE_SECRET_KEY="supabase-secret",
            SECRET_KEY="jwt-secret",
            GOOGLE_API_KEY="google-secret",
        )

        rendered = repr(settings)
        dumped = settings.model_dump()
        safe_dumped = settings.safe_dump()
        redacted_dumped = settings.model_dump_redacted()
        raw_dumped = settings.model_dump(redact_secrets=False)

        for secret in (
            "password",
            "redis-password",
            "supabase-secret",
            "jwt-secret",
            "google-secret",
        ):
            assert secret not in rendered
            assert secret not in str(dumped)
            assert secret not in str(safe_dumped)
            assert secret not in str(redacted_dumped)

        assert Settings.REDACTED_SECRET_VALUE in rendered
        assert dumped["DATABASE_URL"] == Settings.REDACTED_SECRET_VALUE
        assert dumped["REDIS_URL"] == Settings.REDACTED_SECRET_VALUE
        assert dumped["SUPABASE_SECRET_KEY"] == Settings.REDACTED_SECRET_VALUE
        assert dumped["SECRET_KEY"] == Settings.REDACTED_SECRET_VALUE
        assert dumped["GOOGLE_API_KEY"] == Settings.REDACTED_SECRET_VALUE
        assert dumped["SUPABASE_PUBLISHABLE_KEY"] == "sb_publishable_test"
        assert safe_dumped == dumped
        assert redacted_dumped == dumped
        assert raw_dumped["SECRET_KEY"] == "jwt-secret"

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

            assert settings.VASTU_DEFAULT_PROVIDER == "gemini"

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

    def test_auto_blog_defaults(self):
        """Test automated blog publishing defaults."""
        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": "postgresql://localhost/db",
                "SUPABASE_URL": "https://test.supabase.co",
                "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_test",
                "SUPABASE_SECRET_KEY": "test_secret",
                "SENTRY_DSN": "https://test@sentry.io/123",
            },
            clear=False,
        ):
            from importlib import reload

            from app.core import config

            reload(config)

            settings = config.Settings()

            assert settings.AUTO_BLOG_ENABLED is False
            assert settings.AUTO_BLOG_CRON == "0 20 * * *"
            assert settings.AUTO_BLOG_TIMEZONE == "Asia/Kolkata"
            assert settings.AUTO_BLOG_PUBLISHER_USER_ID is None
            assert settings.AUTO_BLOG_MAX_POSTS_PER_RUN == 3
            assert settings.AUTO_BLOG_MODEL == "sonar"

    def test_auto_blog_publisher_user_id_blank_string_is_treated_as_none(self):
        """Test AUTO_BLOG_PUBLISHER_USER_ID accepts blank env values from .env.example."""
        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": "postgresql://localhost/db",
                "SUPABASE_URL": "https://test.supabase.co",
                "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_test",
                "SUPABASE_SECRET_KEY": "test_secret",
                "AUTO_BLOG_ENABLED": "false",
                "AUTO_BLOG_PUBLISHER_USER_ID": "",
            },
            clear=False,
        ):
            from importlib import reload

            from app.core import config

            reload(config)

            settings = config.Settings()
            assert settings.AUTO_BLOG_PUBLISHER_USER_ID is None

    def test_sentry_test_endpoint_requires_opt_in(self):
        """Sentry's intentional crash endpoint is disabled unless explicitly enabled."""
        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": "postgresql://localhost/db",
                "SUPABASE_URL": "https://test.supabase.co",
                "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_test",
                "SUPABASE_SECRET_KEY": "test_secret",
                "ENVIRONMENT": "development",
            },
            clear=False,
        ):
            from importlib import reload

            from app.core import config

            reload(config)

            settings = config.Settings(
                ENABLE_SENTRY_TEST_ENDPOINT=False,
                ENVIRONMENT="development",
            )
            assert settings.sentry_test_endpoint_enabled is False

    def test_sentry_test_endpoint_can_be_enabled_outside_production(self):
        """Sentry's intentional crash endpoint can be mounted for manual non-prod checks."""
        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": "postgresql://localhost/db",
                "SUPABASE_URL": "https://test.supabase.co",
                "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_test",
                "SUPABASE_SECRET_KEY": "test_secret",
                "ENVIRONMENT": "development",
            },
            clear=False,
        ):
            from importlib import reload

            from app.core import config

            reload(config)

            settings = config.Settings(
                ENABLE_SENTRY_TEST_ENDPOINT=True,
                ENVIRONMENT="development",
            )
            assert settings.sentry_test_endpoint_enabled is True

    def test_sentry_test_endpoint_is_never_enabled_in_production(self):
        """Production ignores the Sentry test endpoint flag."""
        with patch.dict(
            os.environ,
            {
                "DATABASE_URL": "postgresql://localhost/db",
                "SUPABASE_URL": "https://test.supabase.co",
                "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_test",
                "SUPABASE_SECRET_KEY": "test_secret",
                "SECRET_KEY": "not-the-default",
                "ENVIRONMENT": "development",
            },
            clear=False,
        ):
            from importlib import reload

            from app.core import config

            reload(config)

            settings = config.Settings(
                ENABLE_SENTRY_TEST_ENDPOINT=True,
                ENVIRONMENT="production",
                SECRET_KEY="not-the-default",
            )
            assert settings.sentry_test_endpoint_enabled is False
