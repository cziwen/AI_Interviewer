import asyncio

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.interview import Interview
from ..models.job_profile import JobProfile
from ..services.realtime import RealtimeSessionRunner
from ..services.realtime.decision_engine import (
    decision_action_to_turn_kind as _decision_action_to_turn_kind,
    parse_and_validate_decision as _parse_and_validate_decision,
)
from ..utils.logger import logger, log_interview_event

router = APIRouter()

# Global registry for active interview tokens to prevent duplicate sessions
active_interview_tokens = set()
active_tokens_lock = asyncio.Lock()


@router.websocket("/ws/{token}")
async def realtime_interview_endpoint(websocket: WebSocket, token: str, db: Session = Depends(get_db)):
    async with active_tokens_lock:
        if token in active_interview_tokens:
            logger.warning("Duplicate WebSocket connection attempt for token: %s. Rejecting.", token)
            await websocket.close(code=4003, reason="Duplicate session")
            return
        active_interview_tokens.add(token)

    interview = None
    try:
        interview = db.query(Interview).filter(Interview.link_token == token).first()
        if not interview:
            logger.warning("WebSocket connection attempt with invalid token: %s", token)
            await websocket.close(code=4004)
            return

        log_interview_event(
            event_name="ws.connected",
            interview_id=interview.id,
            interview_token=token,
            source="api.realtime",
            stage="intro",
            details={"candidate_name": interview.name, "position": interview.position},
        )

        job_profile = db.query(JobProfile).filter(JobProfile.position_name == interview.position).first()
        runner = RealtimeSessionRunner(
            websocket=websocket,
            token=token,
            interview=interview,
            job_profile=job_profile,
        )
        await runner.run()

    except WebSocketDisconnect:
        log_interview_event(
            event_name="ws.disconnected",
            interview_id=interview.id if interview else None,
            interview_token=token,
            source="api.realtime",
            outcome="success",
        )
    except Exception as exc:
        log_interview_event(
            event_name="ws.error",
            interview_id=interview.id if interview else None,
            interview_token=token,
            source="api.realtime",
            outcome="failed",
            error_message=str(exc),
        )
        await websocket.close(code=1011)
    finally:
        async with active_tokens_lock:
            if token in active_interview_tokens:
                active_interview_tokens.remove(token)
