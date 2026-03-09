from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class AdminLogin(BaseModel):
    username: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str

class InterviewSummary(BaseModel):
    id: int
    name: Optional[str]
    position: Optional[str]
    status: str
    created_at: datetime
    total_score: Optional[float] = None

    class Config:
        from_attributes = True
