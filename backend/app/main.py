from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .api import interviews, admin, realtime
from .database import Base, engine
from .utils.logger import logger

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

@app.get("/")
async def root():
    return {"message": "AI Interview API is running"}
