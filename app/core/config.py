from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str = "change-me-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    DATABASE_URL: str
    SUPABASE_URL: str
    SENTRY_DSN: str
    SUPABASE_PUBLISHABLE_KEY: str
    SUPABASE_SECRET_KEY: str
    # API Keys for middleware (comma-separated)
    VALID_API_KEYS: str = ""
    
    # External AI/Search integrations
    PERPLEXITY_API_KEY: Optional[str] = None
    PERPLEXITY_MODEL: str = "sonar"
    
    # Image search via SerpAPI (Google Images)
    SERPAPI_API_KEY: Optional[str] = None
    SERPAPI_SEARCH_ENDPOINT: str = "https://serpapi.com/search.json"
    
    # Gemini AI settings
    GOOGLE_API_KEY: Optional[str] = None
    GEMINI_MODEL: str = "gemini-3-flash-preview"
    GEMINI_EMBED_MODEL: str = "text-embedding-004"

    # GLM (ZhipuAI) API settings for Vastu and other AI features
    GLM_API_KEY: Optional[str] = None
    GLM_API_URL: str = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    GLM_MODEL: str = "glm-4.6v-flash"

    # Vastu analyzer settings
    VASTU_DEFAULT_PROVIDER: str = "glm"  # "gemini" or "glm"
    
    # Vector sync settings
    VECTOR_SYNC_ENABLED: bool = True
    VECTOR_SYNC_CRON: Optional[str] = "0 9 * * *"  # once daily at 9:00 AM
    VECTOR_SYNC_INTERVAL_SECONDS: int = 300  # used when CRON not provided
    VECTOR_SYNC_BATCH_SIZE: int = 500
    VECTOR_SYNC_MAX_RETRIES: int = 3
    
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
    
    REDIS_URL: str = "redis://localhost:6379"
    ENVIRONMENT: str = "development"
    DEBUG: bool = False

    # Public base URL for OAuth/MCP (set when behind ngrok or reverse proxy)
    PUBLIC_BASE_URL: Optional[str] = None  # e.g., https://xyz.ngrok-free.app

    # Public base URL for the frontend app (used for share preview redirects)
    PUBLIC_APP_URL: Optional[str] = None  # e.g., https://360viewer.360ghar.com

    # Cache configuration
    CACHE_BACKEND: str = "memory"  # "memory" or "redis"
    CACHE_DEFAULT_TTL: int = 300  # 5 minutes default
    CACHE_MEMORY_MAX_SIZE: int = 1000  # Max entries for in-memory cache
    CACHE_KEY_PREFIX: str = "ghar360:"  # Redis key prefix

    # Endpoint-specific TTLs (in seconds)
    CACHE_TTL_AMENITIES: int = 86400  # 24 hours
    CACHE_TTL_PROPERTIES_LIST: int = 43200 # 12 hours
    CACHE_TTL_PROPERTY_DETAIL: int = 86400  # 24 hours
    CACHE_TTL_BLOG_POSTS: int = 86400  # 24 hours
    CACHE_TTL_BLOG_CATEGORIES: int = 86400  # 24 hours
    CACHE_TTL_BLOG_TAGS: int = 86400  # 24 hours
    CACHE_TTL_FAQS: int = 86400  # 24 hours
    CACHE_TTL_VERSIONS: int = 86400  # 24 hours
    
    # Supabase Storage - Single unified bucket for all uploads
    SUPABASE_STORAGE_BUCKET: str = "360ghar-storage"

    # Upload limits (applies to presigned upload requests)
    MAX_UPLOAD_SIZE_MB: int = 50

    # Firebase / FCM
    FIREBASE_PROJECT_ID: str | None = None
    GOOGLE_APPLICATION_CREDENTIALS: str | None = None  # path to service account JSON

    # Notifications / Scheduler
    ENABLE_NOTIF_SCHEDULER: bool = False
    NOTIF_SCHED_TZ: str = "Asia/Kolkata"

    # Email notifications (generic provider config)
    EMAIL_SENDER_ADDRESS: Optional[str] = None
    EMAIL_SENDER_NAME: Optional[str] = None
    EMAIL_SMTP_HOST: Optional[str] = None
    EMAIL_SMTP_PORT: int = 587
    EMAIL_SMTP_USERNAME: Optional[str] = None
    EMAIL_SMTP_PASSWORD: Optional[str] = None

    # SMS notifications (generic provider config)
    SMS_PROVIDER_API_URL: Optional[str] = None
    SMS_PROVIDER_API_KEY: Optional[str] = None
    SMS_SENDER_ID: Optional[str] = None
    
    # CORS settings
    CORS_ORIGINS: list = [
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
        "https://admin.360ghar.com",
    # ChatGPT App domains (for widget iframes and MCP calls)
    "https://chatgpt.com",
    "https://chat.openai.com",
    "https://platform.openai.com",
    ]

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        case_sensitive=True,
    )

settings = Settings()
