from pathlib import Path
from dotenv import load_dotenv
from pydantic_settings import BaseSettings
import os

# Load env in a predictable order:
# 1) project root .env (deployment / docker compose)
# 2) backend/.env (local backend-only development overrides)
CURRENT_FILE = Path(__file__).resolve()
BACKEND_DIR = CURRENT_FILE.parents[1]
PROJECT_ROOT = CURRENT_FILE.parents[2]

load_dotenv(PROJECT_ROOT / ".env", override=False)
load_dotenv(BACKEND_DIR / ".env", override=True)

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
    REALTIME_MIN_MAIN_ANSWER_CHARS: int = int(os.getenv("REALTIME_MIN_MAIN_ANSWER_CHARS", "12"))
    REALTIME_MAIN_ANSWER_CONFIRM_WORDS: str = os.getenv("REALTIME_MAIN_ANSWER_CONFIRM_WORDS", "嗯,好,可以,是的,明白,了解,好的,没问题,OK,ok")
    REALTIME_DECISION_LAYER_ENABLED: bool = os.getenv("REALTIME_DECISION_LAYER_ENABLED", "true").lower() == "true"
    REALTIME_DECISION_TIMEOUT_MS: int = int(os.getenv("REALTIME_DECISION_TIMEOUT_MS", "5000"))
    REALTIME_DECISION_HISTORY_TURNS: int = int(os.getenv("REALTIME_DECISION_HISTORY_TURNS", "3"))
    REALTIME_DECISION_MAX_CHARS: int = int(os.getenv("REALTIME_DECISION_MAX_CHARS", "1200"))
    REALTIME_DECISION_MODEL: str = os.getenv("REALTIME_DECISION_MODEL", "gpt-4o-mini")
    
    ADMIN_USERNAME: str = os.getenv("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "admin123")

    class Config:
        env_file = ".env"

settings = Settings()

# Ensure upload directory exists
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
