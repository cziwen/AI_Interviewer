from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks
from sqlalchemy.orm import Session
import secrets
import os
import random
from datetime import datetime
from typing import List

from ..database import get_db, SessionLocal
from ..models.interview import Interview, InterviewStatus
from ..models.job_profile import JobProfile
from ..models.answer import Answer
from ..schemas.interview import InterviewCreate, InterviewResponse, AnswerResponse
from ..services.question_generator import generate_questions
from ..services.stt import transcribe_audio
from ..services.evaluator import evaluate_interview
from ..utils.usage_tracker import InterviewUsageTracker
from ..utils.logger import logger, log_dialogue_line
from ..config import settings

router = APIRouter()

async def process_interview_evaluation(interview_id: int):
    """
    Background task to perform STT and LLM evaluation.
    """
    db = SessionLocal()
    try:
        interview = db.query(Interview).filter(Interview.id == interview_id).first()
        if not interview:
            return

        usage_tracker = InterviewUsageTracker(interview_id=interview.id, interview_token=interview.link_token)
        answers = db.query(Answer).filter(Answer.interview_id == interview.id).all()
        
        # 1. Perform STT for each answer if not already done
        for answer in answers:
            if not answer.transcript and os.path.exists(answer.audio_url):
                transcript, duration = await transcribe_audio(answer.audio_url)
                answer.transcript = transcript
                # Record STT usage
                usage_tracker.add_audio_usage(model_name=settings.STT_MODEL, input_seconds=duration)
                
                # Write to Dialogue Log
                if transcript:
                    log_dialogue_line(
                        interview_token=interview.link_token,
                        role="Candidate",
                        text=transcript,
                        timestamp=answer.created_at.isoformat() + "Z" if answer.created_at else None
                    )
        
        db.commit() # Save transcripts
        
        # 2. LLM Evaluation on all transcripts
        question_map = {q['order_index']: q['question_text'] for q in interview.question_set}
        
        answers_data = [
            {
                "question_index": a.question_index, 
                "question_text": question_map.get(a.question_index, "未知问题"),
                "transcript": a.transcript or ""
            } 
            for a in answers
        ]
        
        evaluation, eval_usage = await evaluate_interview(answers_data)
        
        # Record Eval usage
        usage_tracker.add_text_usage(
            model_name=settings.EVAL_LLM_MODEL,
            input_tokens=eval_usage["input_tokens"],
            output_tokens=eval_usage["output_tokens"]
        )

        interview.evaluation_result = evaluation
        db.commit()

        # Final log of all usage
        usage_tracker.log_summary()
    except Exception as e:
        print(f"Error in background evaluation task: {e}")
    finally:
        db.close()

@router.post("/create", response_model=InterviewResponse)
def create_interview(interview_in: InterviewCreate, db: Session = Depends(get_db)):
    link_token = secrets.token_urlsafe(32)
    
    position = interview_in.position
    questions = []
    
    # Check if position_key is provided to use JobProfile
    if interview_in.position_key:
        job_profile = db.query(JobProfile).filter(JobProfile.position_key == interview_in.position_key).first()
        if not job_profile:
            raise HTTPException(status_code=400, detail=f"Job profile with position_key '{interview_in.position_key}' not found")
        
        position = job_profile.position_name or position
        
        # Determine how many questions to pick from JD (default to 3)
        main_question_count = job_profile.jd_data.get('main_question_count', 3)
        
        # Randomly sample questions from the bank
        bank = job_profile.question_bank
        sample_size = min(main_question_count, len(bank))
        sampled = random.sample(bank, sample_size)
        
        # Re-index for this interview
        questions = [
            {"order_index": i + 1, "question_text": q["question_text"], "reference": q.get("reference")}
            for i, q in enumerate(sampled)
        ]
    else:
        # Fallback to automatic generation
        questions = generate_questions(position, interview_in.resume_brief)
    
    db_interview = Interview(
        name=interview_in.name,
        position=position,
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
    
    # Defer STT to complete stage
    db_answer = Answer(
        interview_id=interview.id,
        question_index=question_index,
        audio_url=file_path,  # Store path
        transcript=None  # To be filled in complete_interview
    )
    db.add(db_answer)
    
    # Update interview status if it's the first answer
    if interview.status == InterviewStatus.CREATED:
        interview.status = InterviewStatus.IN_PROGRESS
    
    db.commit()
    db.refresh(db_answer)
    return db_answer

@router.post("/{token}/complete")
async def complete_interview(token: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    interview = db.query(Interview).filter(Interview.link_token == token).first()
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    
    if interview.status == InterviewStatus.FINISHED:
        return {"message": "Interview already completed"}

    # 1. Update status immediately
    interview.status = InterviewStatus.FINISHED
    interview.completed_at = datetime.utcnow()
    db.commit()
    
    # 2. Add background task for STT and LLM evaluation
    background_tasks.add_task(process_interview_evaluation, interview.id)
    
    return {"message": "Interview submitted successfully"}
