from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str = "change-me-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    DATABASE_URL: str
    SUPABASE_URL: str
    
    SUPABASE_KEY: str
    SUPABASE_SECRET_KEY: str
    
    @property
    def ASYNC_DATABASE_URL(self) -> str:
        """Convert DATABASE_URL to async format for asyncpg"""
        url = self.DATABASE_URL
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        
        # Use direct connection instead of pgbouncer for better SQLAlchemy compatibility
        if ":6543/" in url:
            url = url.replace(":6543/", ":5432/")
        
        return url
    
    REDIS_URL: str = "redis://localhost:6379"
    ENVIRONMENT: str = "development"
    DEBUG: bool = False
    
    # Additional Supabase settings
    SUPABASE_STORAGE_BUCKET: str = "property-images"
    
    # CORS settings
    CORS_ORIGINS: list = [
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
        "https://360ghar.com",
        "https://www.360ghar.com",
    ]
    
    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()