from pydantic_settings import BaseSettings
import os

class Settings(BaseSettings):
    OPENAI_API_KEY: str | None = None
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./ai_interview.db")
    JWT_SECRET: str = os.getenv("JWT_SECRET", "your-secret-key-change-it-in-production")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours
    UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "./app/static/uploads")
    
    # Question Bank Configuration
    QUESTION_BANK_CSV_PATH: str = os.getenv("QUESTION_BANK_CSV_PATH", "app/static/question_bank.csv")
    # JSON string mapping CSV columns to position/level etc. 
    # Example: '{"position": "岗位", "category": "类别"}'
    QUESTION_BANK_FIELD_MAP: str = os.getenv("QUESTION_BANK_FIELD_MAP", '{"position": "岗位"}')
    
    ADMIN_USERNAME: str = os.getenv("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "admin123")

    class Config:
        env_file = ".env"

settings = Settings()

# Ensure upload directory exists
os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
