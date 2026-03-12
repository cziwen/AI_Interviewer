from pydantic_settings import BaseSettings
import os

class Settings(BaseSettings):
    OPENAI_API_KEY: str | None = None
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./ai_interview.db")
    JWT_SECRET: str = os.getenv("JWT_SECRET", "your-secret-key-change-it-in-production")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours
    UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "./app/static/uploads")
    
    # Models for background tasks
    STT_MODEL: str = os.getenv("STT_MODEL", "gpt-4o-mini-transcribe")
    EVAL_LLM_MODEL: str = os.getenv("EVAL_LLM_MODEL", "gpt-4o-mini")
    
    # Realtime Interview Settings
    REALTIME_MODEL: str = os.getenv("REALTIME_MODEL", "gpt-realtime-mini")
    REALTIME_STRICT_PROMPT_ENABLED: bool = os.getenv("REALTIME_STRICT_PROMPT_ENABLED", "true").lower() == "true"
    REALTIME_CONTEXT_RESET_MODE: str = os.getenv("REALTIME_CONTEXT_RESET_MODE", "per_main_question") # none, per_main_question
    
    ADMIN_USERNAME: str = os.getenv("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "admin123")

    class Config:
        env_file = ".env"

settings = Settings()

# Ensure upload directory exists
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
