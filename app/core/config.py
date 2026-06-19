from __future__ import annotations

import os
from pathlib import Path

from pydantic import ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]

_ENV_FILE_MAP = {
    "development": ".env.dev",
    "test": ".env.test",
    "production": ".env.prod",
}
_CURRENT_ENV = os.getenv("ENVIRONMENT", "development")
_ENV_FILE = _ENV_FILE_MAP.get(_CURRENT_ENV, ".env.dev")


class Settings(BaseSettings):
    # ── Core ────────────────────────────────────────────────────────────────────
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str = "change-me-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    APP_VERSION: str = "2.0.0"
    ENVIRONMENT: str = "development"
    DEBUG: bool = False
    SENTRY_DSN: str | None = None
    SENTRY_TRACES_SAMPLE_RATE: float | None = None  # Free tier default: 0.5 dev, 0.05 prod
    VALID_API_KEYS: str = ""  # API keys for middleware (comma-separated)

    # ── Serverless ──────────────────────────────────────────────────────────────
    SERVERLESS_ENABLED: bool = False  # When true, skips in-process schedulers to allow scale-to-zero

    # ── Public URLs ─────────────────────────────────────────────────────────────
    PUBLIC_BASE_URL: str | None = None  # e.g., https://xyz.ngrok-free.app (OAuth/MCP)
    PUBLIC_APP_URL: str | None = None  # e.g., https://360viewer.360ghar.com (share previews)

    # ── CORS ─────────────────────────────────────────────────────────────────────
    # Set CORS_ORIGINS_STR via env to override the default list (comma-separated).
    # Example: CORS_ORIGINS_STR=https://app.example.com,https://admin.example.com
    CORS_ORIGINS_STR: str = ""  # Comma-separated override for CORS origins
    CORS_ORIGINS: list[str] = [
        # Local development
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:8080",
        "http://localhost:55179",
        "http://localhost:54848",
        "http://localhost:4173",
        "http://localhost:4000",
        "http://localhost:5000",
        "http://localhost:6000",
        "http://localhost:7000",
        "http://localhost:9000",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:8080",
        "http://127.0.0.1:55179",
        "http://127.0.0.1:54848",
        "http://127.0.0.1:4173",
        "http://127.0.0.1:4000",
        "http://127.0.0.1:5000",
        "http://127.0.0.1:6000",
        "http://127.0.0.1:7000",
        "http://127.0.0.1:9000",
        # Production domains
        "https://360ghar.com",
        "https://www.360ghar.com",
        "https://flatmates.360ghar.com",
        "https://admin.360ghar.com",
        # ChatGPT App domains (for widget iframes and MCP calls)
        "https://chatgpt.com",
        "https://chat.openai.com",
        "https://platform.openai.com",
    ]

    @field_validator("CORS_ORIGINS", mode="after")
    @classmethod
    def _cors_origins_from_env(cls, value: list[str], info: ValidationInfo) -> list[str]:
        """Override CORS_ORIGINS from CORS_ORIGINS_STR if provided."""
        origins_str = info.data.get("CORS_ORIGINS_STR", "")
        if origins_str and origins_str.strip():
            origins = [origin.strip() for origin in origins_str.split(",") if origin.strip()]
            for origin in origins:
                if not origin.startswith(("http://", "https://")):
                    raise ValueError(
                        f"Invalid CORS origin: {origin!r}. Must start with http:// or https://"
                    )
            return origins
        return value

    @field_validator("SECRET_KEY", mode="after")
    @classmethod
    def _secret_key_not_default_in_production(cls, value: str, info: ValidationInfo) -> str:
        env = info.data.get("ENVIRONMENT", "development")
        if value == "change-me-in-production" and env == "production":
            raise ValueError("SECRET_KEY must be changed from default in production environment")
        return value

    # ── Database & Supabase ──────────────────────────────────────────────────────
    DATABASE_URL: str
    SUPABASE_URL: str
    SUPABASE_PUBLISHABLE_KEY: str
    SUPABASE_SECRET_KEY: str
    # HMAC secret used to verify inbound Supabase webhooks (e.g. password-changed
    # session revocation). Empty by default; must be set in production.
    SUPABASE_WEBHOOK_SECRET: str = ""
    # Encoding of the X-Supabase-Signature header: "hex" (default) or "base64".
    SUPABASE_WEBHOOK_SIGNATURE_ENCODING: str = "hex"
    REDIS_URL: str = "redis://localhost:6379"

    # Main pool (HTTP/MCP request traffic)
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 5
    DB_POOL_TIMEOUT: int = 15
    DB_POOL_RECYCLE: int = 180
    # Background pool (schedulers, scrapers, long-running tasks)
    DB_BG_POOL_SIZE: int = 2
    DB_BG_MAX_OVERFLOW: int = 2

    @property
    def ASYNC_DATABASE_URL(self) -> str:
        """Convert DATABASE_URL to async format for psycopg (better PgBouncer support)"""
        url = self.DATABASE_URL
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)
        elif url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+psycopg://", 1)
        return url

    @property
    def SUPABASE_CLIENT_KEY(self) -> str:
        """Return the key used for non-privileged Supabase auth flows."""
        return self.SUPABASE_PUBLISHABLE_KEY.strip()

    # ── Google OAuth client IDs (surfaced to clients via /api/v1/auth/config) ───
    GOOGLE_WEB_CLIENT_ID: str | None = None
    GOOGLE_IOS_CLIENT_ID: str | None = None
    GOOGLE_ANDROID_CLIENT_ID: str | None = None

    # ── Cache ────────────────────────────────────────────────────────────────────
    CACHE_BACKEND: str = "disk"  # "disk", "memory", or "redis"
    CACHE_DEFAULT_TTL: int = 300  # 5 minutes default
    CACHE_MEMORY_MAX_SIZE: int = 1000  # Max entries for in-memory cache
    CACHE_MEMORY_MAX_ENTRY_BYTES: int = 1_000_000
    # Disk cache path — use a persistent volume in Docker to survive restarts
    CACHE_DISK_DIR: str = "./cache"
    CACHE_DISK_MAX_SIZE: int = 1000
    CACHE_DISK_MAX_ENTRY_BYTES: int = 1_000_000
    CACHE_REDIS_MAX_CONNECTIONS: int = 15
    CACHE_KEY_PREFIX: str = "ghar360:"  # Redis key prefix
    # Endpoint-specific TTLs (in seconds)
    CACHE_TTL_AMENITIES: int = 86400  # 24 hours
    CACHE_TTL_PROPERTIES_LIST: int = 43200  # 12 hours
    CACHE_TTL_PROPERTY_DETAIL: int = 86400  # 24 hours
    CACHE_TTL_BLOG_POSTS: int = 86400  # 24 hours
    CACHE_TTL_BLOG_CATEGORIES: int = 86400  # 24 hours
    CACHE_TTL_BLOG_TAGS: int = 86400  # 24 hours
    CACHE_TTL_FAQS: int = 86400  # 24 hours
    CACHE_TTL_VERSIONS: int = 86400  # 24 hours

    # ── AI Providers ─────────────────────────────────────────────────────────────
    # Gemini
    GOOGLE_API_KEY: str | None = None
    GEMINI_MODEL: str = "gemini-3.1-flash-lite-preview"
    GEMINI_EMBED_MODEL: str = "text-embedding-004"
    # GLM (ZhipuAI) — used for Vastu and other AI features
    GLM_API_KEY: str | None = None
    GLM_API_URL: str = "https://api.z.ai/api/coding/paas/v4/chat/completions"
    GLM_MODEL: str = "glm-5v-turbo"
    # Vastu analyzer
    VASTU_DEFAULT_PROVIDER: str = "glm"  # "gemini" or "glm"
    VASTU_FALLBACK_PROVIDER: str = ""  # Auto-derived if empty (swaps to the other provider)
    # Pydantic AI Agent — fallback chain: GLM -> Gemini -> Groq
    AI_AGENT_MODEL: str = "glm-4.7-flash"  # ZhipuAI GLM-4.7-Flash (primary)
    AI_AGENT_API_BASE: str = "https://api.z.ai/api/coding/paas/v4"
    AI_AGENT_API_KEY: str | None = None  # Defaults to GLM_API_KEY
    AI_AGENT_FALLBACK_MODEL: str | None = None
    AI_AGENT_FALLBACK_API_BASE: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    AI_AGENT_FALLBACK_API_KEY: str | None = None  # Defaults to GOOGLE_API_KEY
    AI_AGENT_FALLBACK2_MODEL: str = "qwen/qwen3-32b"
    AI_AGENT_FALLBACK2_API_BASE: str = "https://api.groq.com/openai/v1"
    AI_AGENT_FALLBACK2_API_KEY: str | None = None  # Groq API key
    AI_AGENT_MAX_TOKENS: int = 64096
    AI_AGENT_TEMPERATURE: float = 0.7
    AI_AGENT_MAX_HISTORY: int = 50
    # Groq
    GROQ_API_KEY: str | None = None
    GROQ_MODEL: str = "qwen/qwen3-32b"
    GROQ_API_BASE: str = "https://api.groq.com/openai/v1"
    # Perplexity (web search for blog & agent)
    PERPLEXITY_API_KEY: str | None = None
    PERPLEXITY_MODEL: str = "sonar"
    # SerpAPI (Google Images search for blog)
    SERPAPI_API_KEY: str | None = None
    SERPAPI_SEARCH_ENDPOINT: str = "https://serpapi.com/search.json"
    # Image APIs (blog cover image acquisition)
    PIXABAY_API_KEY: str | None = None
    PEXELS_API_KEY: str | None = None

    # ── Blog Auto-Publish ────────────────────────────────────────────────────────
    AUTO_BLOG_ENABLED: bool = False
    AUTO_BLOG_CRON: str = "0 20 * * *"
    AUTO_BLOG_TIMEZONE: str = "Asia/Kolkata"
    AUTO_BLOG_PUBLISHER_USER_ID: int | None = None
    AUTO_BLOG_MAX_POSTS_PER_RUN: int = 3
    AUTO_BLOG_MODEL: str = "sonar"

    @field_validator("AUTO_BLOG_PUBLISHER_USER_ID", mode="before")
    @classmethod
    def _blank_auto_blog_publisher_user_id_is_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    # ── Notifications ────────────────────────────────────────────────────────────
    ENABLE_NOTIF_SCHEDULER: bool = False
    NOTIF_SCHED_TZ: str = "Asia/Kolkata"
    # Email
    EMAIL_SENDER_ADDRESS: str | None = None
    EMAIL_SENDER_NAME: str | None = None
    EMAIL_SMTP_HOST: str | None = None
    EMAIL_SMTP_PORT: int = 587
    EMAIL_SMTP_USERNAME: str | None = None
    EMAIL_SMTP_PASSWORD: str | None = None
    # SMS
    SMS_PROVIDER_API_URL: str | None = None
    SMS_PROVIDER_API_KEY: str | None = None
    SMS_SENDER_ID: str | None = None
    # Firebase / FCM push
    FIREBASE_PROJECT_ID: str | None = None
    GOOGLE_APPLICATION_CREDENTIALS: str | None = None  # path to service account JSON

    # ── Visits ──────────────────────────────────────────────────────────────────
    # Each visit is treated as occupying a fixed-duration window starting at
    # scheduled_date (the Visit model has no explicit duration column).
    VISIT_DEFAULT_DURATION_MINUTES: int = 60
    # Buffer (in minutes) applied to both sides of the overlap check so that
    # back-to-back visits are still considered conflicting.
    VISIT_CONFLICT_BUFFER_MINUTES: int = 0

    # ── Storage ──────────────────────────────────────────────────────────────────
    CLOUDINARY_CLOUD_NAME: str = ""
    CLOUDINARY_API_KEY: str = ""
    CLOUDINARY_API_SECRET: str = ""
    MAX_UPLOAD_SIZE_MB: int = 50

    # ── Tax & Service Rates ────────────────────────────────────────────────────
    GST_RATE: float = 0.18  # 18% GST for booking tax calculation
    SERVICE_CHARGE_RATE: float = 0.05  # 5% service charge for bookings

    # ── Razorpay (payments) ────────────────────────────────────────────────────
    RAZORPAY_KEY_ID: str | None = None
    RAZORPAY_SECRET: str | None = None
    RAZORPAY_WEBHOOK_SECRET: str | None = None
    RAZORPAY_CURRENCY: str = "INR"

    # ── Data Hub ────────────────────────────────────────────────────────────────
    DATA_HUB_ENABLED: bool = True
    GOOGLE_PLACES_API_KEY: str | None = None
    GOOGLE_PLACES_MAX_DAILY_CALLS: int = 1000
    NEIGHBOURHOOD_SCORE_RADIUS_M: int = 1500
    NEIGHBOURHOOD_SCORE_STALE_DAYS: int = 30
    JAMABANDI_CACHE_TTL_DAYS: int = 7
    # Haryana stamp duty rates (as percentages for display, not computation)
    STAMP_DUTY_RATE_MALE: float = 7.0
    STAMP_DUTY_RATE_FEMALE: float = 5.0
    STAMP_DUTY_RATE_JOINT: float = 6.0

    # ── Vector Embeddings & Sync ────────────────────────────────────────────────
    VECTOR_SYNC_ENABLED: bool = True
    VECTOR_SYNC_CRON: str | None = "0 9 * * *"  # once daily at 9:00 AM
    VECTOR_SYNC_INTERVAL_SECONDS: int = 86400  # used when CRON not provided (daily)
    VECTOR_SYNC_BATCH_SIZE: int = 500
    VECTOR_SYNC_MAX_RETRIES: int = 3

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / _ENV_FILE),
        case_sensitive=True,
        extra="ignore",
    )


settings = Settings()  # type: ignore[call-arg]
