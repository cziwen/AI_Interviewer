from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from typing import List

from ..database import get_db
from ..models.admin_user import AdminUser
from ..models.interview import Interview
from ..schemas.admin import AdminLogin, Token, InterviewSummary
from ..services.auth import verify_password, create_access_token, get_password_hash
from ..config import settings

router = APIRouter()

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/admin/login")

@router.post("/login", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    # Check if admin user exists, if not create from settings
    admin = db.query(AdminUser).filter(AdminUser.username == form_data.username).first()
    if not admin:
        if form_data.username == settings.ADMIN_USERNAME and form_data.password == settings.ADMIN_PASSWORD:
            # Create the admin user in DB
            admin = AdminUser(
                username=settings.ADMIN_USERNAME,
                password_hash=get_password_hash(settings.ADMIN_PASSWORD)
            )
            db.add(admin)
            db.commit()
            db.refresh(admin)
        else:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect username or password",
                headers={"WWW-Authenticate": "Bearer"},
            )
    
    if not verify_password(form_data.password, admin.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token = create_access_token(data={"sub": admin.username})
    return {"access_token": access_token, "token_type": "bearer"}

@router.get("/interviews", response_model=List[InterviewSummary])
def list_interviews(db: Session = Depends(get_db)):
    interviews = db.query(Interview).all()
    # Map to summary including score from JSON
    results = []
    for i in interviews:
        score = i.evaluation_result.get("total_score") if i.evaluation_result else None
        results.append(InterviewSummary(
            id=i.id,
            name=i.name,
            position=i.position,
            status=i.status,
            created_at=i.created_at,
            total_score=score
        ))
    return results

@router.get("/interviews/{interview_id}")
def get_interview_detail(interview_id: int, db: Session = Depends(get_db)):
    interview = db.query(Interview).filter(Interview.id == interview_id).first()
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")
    
    from ..models.answer import Answer
    answers = db.query(Answer).filter(Answer.interview_id == interview.id).all()
    
    return {
        "interview": interview,
        "answers": answers
    }
