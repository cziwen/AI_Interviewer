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
    ARK_API_KEY: str | None = None
    ARK_BASE_URL: str = os.getenv("ARK_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
    ARK_ASR_WS_URL: str = os.getenv("ARK_ASR_WS_URL", "wss://ai-gateway.vei.volces.com/v1/realtime?model=bigmodel")
    ARK_ASR_RESOURCE_ID: str = os.getenv("ARK_ASR_RESOURCE_ID", "")
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./ai_interview.db")
    JWT_SECRET: str = os.getenv("JWT_SECRET", "your-secret-key-change-it-in-production")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours
    UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "./app/static/uploads")
    
    # Models for background tasks
    ARK_LLM_MODEL: str = os.getenv("ARK_LLM_MODEL", "doubao-seed-2-0-mini-260215")
    ARK_STT_MODEL: str = os.getenv("ARK_STT_MODEL", "Doubao-语音识别")
    ARK_CHAT_MODEL: str = os.getenv("ARK_CHAT_MODEL", os.getenv("ARK_LLM_MODEL", "doubao-seed-2-0-mini-260215"))
    ARK_EVAL_MODEL: str = os.getenv("ARK_EVAL_MODEL", os.getenv("ARK_LLM_MODEL", "doubao-seed-2-0-mini-260215"))
    ARK_DECISION_MODEL: str = os.getenv("ARK_DECISION_MODEL", os.getenv("ARK_LLM_MODEL", "doubao-seed-2-0-mini-260215"))
    ARK_TTS_MODEL: str = os.getenv("ARK_TTS_MODEL", "Doubao-语音合成")
    ARK_TTS_VOICE: str = os.getenv("ARK_TTS_VOICE", "zh_female_meilinvyou_moon_bigtts")
    ARK_TTS_SAMPLE_RATE: int = int(os.getenv("ARK_TTS_SAMPLE_RATE", "24000"))
    
    # Realtime Interview Settings
    REALTIME_STRICT_PROMPT_ENABLED: bool = os.getenv("REALTIME_STRICT_PROMPT_ENABLED", "true").lower() == "true"
    REALTIME_CONTEXT_RESET_MODE: str = os.getenv("REALTIME_CONTEXT_RESET_MODE", "per_main_question") # none, per_main_question
    REALTIME_MIN_MAIN_ANSWER_CHARS: int = int(os.getenv("REALTIME_MIN_MAIN_ANSWER_CHARS", "12"))
    REALTIME_MAIN_ANSWER_CONFIRM_WORDS: str = os.getenv("REALTIME_MAIN_ANSWER_CONFIRM_WORDS", "嗯,好,可以,是的,明白,了解,好的,没问题,OK,ok")
    REALTIME_DECISION_LAYER_ENABLED: bool = os.getenv("REALTIME_DECISION_LAYER_ENABLED", "true").lower() == "true"
    REALTIME_DECISION_TIMEOUT_MS: int = int(os.getenv("REALTIME_DECISION_TIMEOUT_MS", "5000"))
    REALTIME_DECISION_HISTORY_TURNS: int = int(os.getenv("REALTIME_DECISION_HISTORY_TURNS", "3"))
    REALTIME_DECISION_MAX_CHARS: int = int(os.getenv("REALTIME_DECISION_MAX_CHARS", "1200"))
    ADMIN_USERNAME: str = os.getenv("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "admin123")

    class Config:
        env_file = ".env"

settings = Settings()

# Ensure upload directory exists
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
