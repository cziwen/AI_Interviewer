from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
import secrets
import os
from datetime import datetime
from typing import List

from ..database import get_db
from ..models.interview import Interview, InterviewStatus
from ..models.answer import Answer
from ..schemas.interview import InterviewCreate, InterviewResponse, AnswerResponse
from ..services.question_generator import generate_questions
from ..services.stt import transcribe_audio
from ..services.evaluator import evaluate_interview
from ..config import settings

router = APIRouter()

@router.post("/create", response_model=InterviewResponse)
def create_interview(interview_in: InterviewCreate, db: Session = Depends(get_db)):
    link_token = secrets.token_urlsafe(32)
    questions = generate_questions(interview_in.position, interview_in.resume_brief)
    
    db_interview = Interview(
        name=interview_in.name,
        position=interview_in.position,
        external_id=interview_in.external_id,
        resume_brief=interview_in.resume_brief,
        link_token=link_token,
        question_set=questions,
        status=InterviewStatus.CREATED
    )
    db.add(db_interview)
    db.commit()
    db.refresh(db_interview)
    return db_interview

@router.get("/{token}", response_model=InterviewResponse)
def get_interview(token: str, db: Session = Depends(get_db)):
    interview = db.query(Interview).filter(Interview.link_token == token).first()
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    return interview

@router.post("/{token}/answer", response_model=AnswerResponse)
async def submit_answer(
    token: str,
    question_index: int = Form(...),
    audio_file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    interview = db.query(Interview).filter(Interview.link_token == token).first()
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    
    # Save audio file
    file_ext = os.path.splitext(audio_file.filename)[1]
    file_name = f"{token}_{question_index}_{secrets.token_hex(4)}{file_ext}"
    file_path = os.path.join(settings.UPLOAD_DIR, file_name)
    
    with open(file_path, "wb") as buffer:
        buffer.write(await audio_file.read())
    
    # STT (Placeholder)
    transcript = await transcribe_audio(file_path)
    
    db_answer = Answer(
        interview_id=interview.id,
        question_index=question_index,
        audio_url=file_path,  # In production, this might be a URL to S3
        transcript=transcript
    )
    db.add(db_answer)
    
    # Update interview status if it's the first answer
    if interview.status == InterviewStatus.CREATED:
        interview.status = InterviewStatus.IN_PROGRESS
    
    db.commit()
    db.refresh(db_answer)
    return db_answer

@router.post("/{token}/complete")
async def complete_interview(token: str, db: Session = Depends(get_db)):
    interview = db.query(Interview).filter(Interview.link_token == token).first()
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    
    answers = db.query(Answer).filter(Answer.interview_id == interview.id).all()
    
    # LLM Evaluation (Placeholder)
    answers_data = [{"question_index": a.question_index, "transcript": a.transcript} for a in answers]
    evaluation = await evaluate_interview(answers_data)
    
    interview.status = InterviewStatus.FINISHED
    interview.evaluation_result = evaluation
    interview.completed_at = datetime.utcnow()
    
    db.commit()
    return {"message": "Interview completed", "evaluation": evaluation}
