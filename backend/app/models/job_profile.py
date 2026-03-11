from sqlalchemy import Column, Integer, String, DateTime, JSON
from datetime import datetime
from ..database import Base

class JobProfile(Base):
    __tablename__ = "job_profiles"

    id = Column(Integer, primary_key=True, index=True)
    position_key = Column(String, unique=True, index=True)  # 岗位唯一标识，如 "backend_engineer"
    position_name = Column(String, nullable=True)          # 展示名称，如 "后端工程师"
    jd_data = Column(JSON)                                 # 存储 JD JSON 的结构化数据
    question_bank = Column(JSON)                           # 存储从 CSV 解析出的题目列表 [{question_text, reference}]
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
