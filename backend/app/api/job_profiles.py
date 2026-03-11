import json
import csv
import io
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import List, Optional
from ..database import get_db
from ..models.job_profile import JobProfile
from pydantic import BaseModel

router = APIRouter()

class JobProfileResponse(BaseModel):
    position_key: str
    position_name: Optional[str]
    jd_data: dict
    question_bank: List[dict]

    class Config:
        from_attributes = True

@router.post("/", response_model=JobProfileResponse)
async def create_or_update_job_profile(
    position_key: str = Form(...),
    position_name: Optional[str] = Form(None),
    jd_file: UploadFile = File(...),
    question_csv: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    # 1. Parse JD JSON
    try:
        jd_content = await jd_file.read()
        jd_data = json.loads(jd_content)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse JD JSON: {str(e)}")

    # 2. Parse Question CSV
    question_bank = []
    try:
        csv_content = await question_csv.read()
        csv_reader = csv.DictReader(io.StringIO(csv_content.decode('utf-8-sig')))
        
        # Expecting columns: 'question', 'reference'
        for row in csv_reader:
            question_text = row.get('question', '').strip()
            reference = row.get('reference', '').strip()
            if question_text:
                question_bank.append({
                    "question_text": question_text,
                    "reference": reference or None
                })
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse Question CSV: {str(e)}")

    if not question_bank:
        raise HTTPException(status_code=400, detail="Question bank is empty or CSV format is incorrect (need 'question' and 'reference' columns)")

    # 3. Save to DB
    db_profile = db.query(JobProfile).filter(JobProfile.position_key == position_key).first()
    if db_profile:
        db_profile.position_name = position_name or db_profile.position_name
        db_profile.jd_data = jd_data
        db_profile.question_bank = question_bank
    else:
        db_profile = JobProfile(
            position_key=position_key,
            position_name=position_name,
            jd_data=jd_data,
            question_bank=question_bank
        )
        db.add(db_profile)
    
    db.commit()
    db.refresh(db_profile)
    return db_profile

@router.get("/", response_model=List[JobProfileResponse])
def list_job_profiles(db: Session = Depends(get_db)):
    return db.query(JobProfile).all()

@router.get("/{position_key}", response_model=JobProfileResponse)
def get_job_profile(position_key: str, db: Session = Depends(get_db)):
    db_profile = db.query(JobProfile).filter(JobProfile.position_key == position_key).first()
    if not db_profile:
        raise HTTPException(status_code=404, detail="Job profile not found")
    return db_profile
