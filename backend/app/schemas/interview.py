from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime

class Question(BaseModel):
    order_index: int
    question_text: str

class InterviewCreate(BaseModel):
    name: Optional[str] = None
    position: Optional[str] = None
    external_id: Optional[str] = None
    resume_brief: Optional[str] = None

class InterviewResponse(BaseModel):
    id: int
    name: Optional[str]
    position: Optional[str]
    status: str
    link_token: str
    question_set: List[Question]
    created_at: datetime

    class Config:
        from_attributes = True

class AnswerCreate(BaseModel):
    question_index: int

class AnswerResponse(BaseModel):
    id: int
    question_index: int
    audio_url: str
    transcript: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True
