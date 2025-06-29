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
    
    REDIS_URL: str = "redis://localhost:6379"
    ENVIRONMENT: str = "development"
    
    # Additional Supabase settings
    SUPABASE_STORAGE_BUCKET: str = "property-images"
    
    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()