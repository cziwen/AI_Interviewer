from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from datetime import datetime
from ..database import Base

class Answer(Base):
    __tablename__ = "answers"

    id = Column(Integer, primary_key=True, index=True)
    interview_id = Column(Integer, ForeignKey("interviews.id"))
    question_index = Column(Integer)
    audio_url = Column(String)
    transcript = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
