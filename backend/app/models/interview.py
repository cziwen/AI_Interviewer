from sqlalchemy import Column, Integer, String, DateTime, JSON, Enum
from datetime import datetime
import enum
from ..database import Base

class InterviewStatus(str, enum.Enum):
    CREATED = "created"
    IN_PROGRESS = "in_progress"
    FINISHED = "finished"
    EVALUATED = "evaluated"

class Interview(Base):
    __tablename__ = "interviews"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=True)
    position = Column(String, nullable=True)
    external_id = Column(String, nullable=True)
    resume_brief = Column(String, nullable=True)
    status = Column(String, default=InterviewStatus.CREATED)
    link_token = Column(String, unique=True, index=True)
    question_set = Column(JSON)  # List of {order_index, question_text}
    evaluation_result = Column(JSON, nullable=True)  # {total_score, dimension_scores, comment}
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
