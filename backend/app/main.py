from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .api import interviews, admin, realtime, job_profiles
from .database import Base, engine
from .utils.logger import logger
from .models import job_profile  # Ensure model is registered for create_all
from .models import admin_user  # Ensure admin_users table is created

# Create tables
Base.metadata.create_all(bind=engine)

app = FastAPI(title="AI Interview")

logger.info("AI Interview API starting up...")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(interviews.router, prefix="/api/interviews", tags=["interviews"])
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])
app.include_router(realtime.router, prefix="/api/realtime", tags=["realtime"])
app.include_router(job_profiles.router, prefix="/api/job_profiles", tags=["job_profiles"])

@app.get("/")
async def root():
    return {"message": "AI Interview API is running"}
