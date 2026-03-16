"""
Realtime Turn Orchestrator
Manages turn lifecycle and business state transitions for realtime interviews.
"""

import time
from dataclasses import dataclass, field
from typing import Optional, Dict, List
from enum import Enum
from ..utils.logger import log_interview_event


class TurnKind(str, Enum):
    """Types of turns in the interview flow"""
    INTRO_PROMPT = "intro_prompt"
    MAIN_PROMPT = "main_prompt"
    FOLLOWUP_PROMPT = "followup_prompt"
    REASK_PROMPT = "reask_prompt"
    CLOSING_PROMPT = "closing_prompt"
    HARD_TIMEOUT_PROMPT = "hard_timeout_prompt"
    HR_REDIRECT_PROMPT = "hr_redirect_prompt"


class TurnStatus(str, Enum):
    """Status of a turn in its lifecycle"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class InterviewStage(str, Enum):
    """Interview stages"""
    INTRO = "intro"
    QA = "qa"
    CLOSING = "closing"


@dataclass
class TurnContext:
    """Represents a single turn in the conversation"""
    turn_id: int
    turn_kind: TurnKind
    stage: InterviewStage
    question_order: int
    expected_reply_before_turn: Optional[str]
    instructions_preview: str
    target_question_order: Optional[int] = None
    target_expected_reply: Optional[str] = None
    status: TurnStatus = TurnStatus.PENDING
    response_id: Optional[str] = None
    transcript: str = ""
    cancel_reason: Optional[str] = None
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    created_ts: float = field(default_factory=time.time)
    completed_ts: Optional[float] = None

    def to_log_dict(self) -> dict:
        """Convert to dictionary for logging"""
        return {
            "turn_id": self.turn_id,
            "turn_kind": self.turn_kind.value,
            "stage": self.stage.value,
            "question_order": self.question_order,
            "expected_reply_before_turn": self.expected_reply_before_turn,
            "target_question_order": self.target_question_order,
            "target_expected_reply": self.target_expected_reply,
            "status": self.status.value,
            "response_id": self.response_id,
            "transcript_len": len(self.transcript),
            "cancel_reason": self.cancel_reason,
            "error_code": self.error_code,
            "duration": self.completed_ts - self.created_ts if self.completed_ts else None
        }


@dataclass
class TurnPlan:
    """Plan for the next turn after candidate input"""
    turn_kind: TurnKind
    stage_after_completion: InterviewStage
    question_order_after_completion: int
    expected_reply_after_completion: Optional[str]
    control_instruction: str
    advance_main_completed: bool = False
    next_followups_used: int = 0
    next_clarifies_used: int = 0

    def to_log_dict(self) -> dict:
        """Convert to dictionary for logging"""
        return {
            "turn_kind": self.turn_kind.value,
            "stage_after": self.stage_after_completion.value,
            "question_order_after": self.question_order_after_completion,
            "expected_reply_after": self.expected_reply_after_completion,
            "advance_main": self.advance_main_completed,
            "instruction_preview": self.control_instruction[:100] if self.control_instruction else None
        }


@dataclass
class BusinessTransition:
    """Represents a business state transition after turn completion"""
    new_stage: InterviewStage
    new_question_order: int
    new_expected_reply: Optional[str]
    advance_main_completed: bool
    new_followups_used: int
    new_clarifies_used: int = 0
    is_natural_end: bool = False


class RealtimeTurnOrchestrator:
    """Orchestrates turn management for realtime interviews"""

    def __init__(self, token: str, candidate_name: str, position: str):
        self.token = token
        self.candidate_name = candidate_name
        self.position = position

        # Turn management
        self.turn_seq = 0
        self.active_turn_id: Optional[int] = None
        self.turns_by_id: Dict[int, TurnContext] = {}
        self.response_to_turn: Dict[str, int] = {}
        self.last_completed_turn_id: Optional[int] = None
        self.last_cancelled_turn_id: Optional[int] = None

        # Transcript buffers per response
        self.transcript_buffers: Dict[str, List[str]] = {}

        # Statistics
        self.turns_created = 0
        self.turns_completed = 0
        self.turns_cancelled = 0
        self.turns_failed = 0

        # User transcript tracking
        self.user_transcripts: Dict[str, str] = {}

    def next_turn_id(self) -> int:
        """Generate next turn ID"""
        self.turn_seq += 1
        return self.turn_seq

    def create_turn(self, plan: TurnPlan, current_stage: InterviewStage,
                   expected_reply_before: Optional[str], question_order: int) -> TurnContext:
        """Create a new turn from a plan"""
        turn_id = self.next_turn_id()
        turn = TurnContext(
            turn_id=turn_id,
            turn_kind=plan.turn_kind,
            stage=current_stage,
            question_order=question_order,
            expected_reply_before_turn=expected_reply_before,
            instructions_preview=plan.control_instruction[:200] if plan.control_instruction else "",
            target_question_order=plan.question_order_after_completion,
            target_expected_reply=plan.expected_reply_after_completion
        )

        self.turns_by_id[turn_id] = turn
        self.active_turn_id = turn_id
        self.turns_created += 1

        log_interview_event(
            event_name="turn.created",
            interview_token=self.token,
            source="turn_orchestrator",
            stage=current_stage.value,
            turn_id=str(turn_id),
            details=turn.to_log_dict(),
            question_order=question_order,
            turn_kind=turn.turn_kind.value
        )
        return turn

    def bind_response(self, response_id: str) -> Optional[TurnContext]:
        """Bind a response.created event to the active turn"""
        if not self.active_turn_id:
            return None

        turn = self.turns_by_id.get(self.active_turn_id)
        if not turn:
            return None

        if turn.response_id and turn.response_id != response_id:
            return None

        turn.response_id = response_id
        turn.status = TurnStatus.IN_PROGRESS
        self.response_to_turn[response_id] = turn.turn_id

        # Initialize transcript buffer for this response
        self.transcript_buffers[response_id] = []

        return turn

    def append_transcript_delta(self, response_id: str, delta: str) -> None:
        """Append transcript delta to the correct response buffer"""
        if response_id not in self.transcript_buffers:
            self.transcript_buffers[response_id] = []
        self.transcript_buffers[response_id].append(delta)

    def complete_turn(self, response_id: str, usage: Optional[dict] = None) -> Optional[TurnContext]:
        """Mark a turn as completed"""
        turn_id = self.response_to_turn.get(response_id)
        if not turn_id:
            return None

        turn = self.turns_by_id.get(turn_id)
        if not turn:
            return None

        # Assemble full transcript
        if response_id in self.transcript_buffers:
            turn.transcript = "".join(self.transcript_buffers[response_id])

        turn.status = TurnStatus.COMPLETED
        turn.completed_ts = time.time()
        self.last_completed_turn_id = turn_id
        self.turns_completed += 1

        # Clear active turn
        if self.active_turn_id == turn_id:
            self.active_turn_id = None

        log_data = turn.to_log_dict()
        if usage:
            log_data["usage"] = usage

        log_interview_event(
            event_name="turn.completed",
            interview_token=self.token,
            source="turn_orchestrator",
            turn_id=str(turn_id),
            outcome="success",
            details=log_data,
            duration_ms=int((turn.completed_ts - turn.created_ts) * 1000) if turn.completed_ts else None,
            upstream_response_id=response_id
        )
        return turn

    def cancel_turn(self, response_id: str, reason: str) -> Optional[TurnContext]:
        """Mark a turn as cancelled"""
        turn_id = self.response_to_turn.get(response_id)
        if not turn_id:
            return None

        turn = self.turns_by_id.get(turn_id)
        if not turn:
            return None

        # Assemble partial transcript if any
        if response_id in self.transcript_buffers:
            turn.transcript = "".join(self.transcript_buffers[response_id])

        turn.status = TurnStatus.CANCELLED
        turn.cancel_reason = reason
        turn.completed_ts = time.time()
        self.last_cancelled_turn_id = turn_id
        self.turns_cancelled += 1

        # Clear active turn
        if self.active_turn_id == turn_id:
            self.active_turn_id = None

        log_interview_event(
            event_name="turn.cancelled",
            interview_token=self.token,
            source="turn_orchestrator",
            turn_id=str(turn_id),
            outcome="cancelled",
            details=turn.to_log_dict(),
            upstream_response_id=response_id
        )
        return turn

    def set_user_transcript(self, item_id: str, transcript: str) -> None:
        """Store user transcript for a conversation item"""
        self.user_transcripts[item_id] = transcript
        log_interview_event(
            event_name="user_transcription.completed",
            interview_token=self.token,
            source="turn_orchestrator",
            details={
                "item_id": item_id,
                "transcript_len": len(transcript)
            }
        )

    def get_user_transcript(self, item_id: str) -> Optional[str]:
        """Get user transcript for a conversation item"""
        return self.user_transcripts.get(item_id)


    def fail_turn(self, response_id: str, error_code: str, error_message: str) -> Optional[TurnContext]:
        """Mark a turn as failed"""
        turn_id = self.response_to_turn.get(response_id) if response_id else self.active_turn_id
        if not turn_id:
            return None

        turn = self.turns_by_id.get(turn_id)
        if not turn:
            return None

        turn.status = TurnStatus.FAILED
        turn.error_code = error_code
        turn.error_message = error_message
        turn.completed_ts = time.time()
        self.turns_failed += 1

        # Clear active turn
        if self.active_turn_id == turn_id:
            self.active_turn_id = None

        log_interview_event(
            event_name="turn.failed",
            interview_token=self.token,
            source="turn_orchestrator",
            turn_id=str(turn_id),
            outcome="failed",
            error_code=error_code,
            error_message=error_message,
            details=turn.to_log_dict(),
            upstream_response_id=response_id
        )
        return turn

    def get_active_turn(self) -> Optional[TurnContext]:
        """Get the currently active turn"""
        if not self.active_turn_id:
            return None
        return self.turns_by_id.get(self.active_turn_id)

    def get_last_completed_turn(self) -> Optional[TurnContext]:
        """Get the last completed turn"""
        if not self.last_completed_turn_id:
            return None
        return self.turns_by_id.get(self.last_completed_turn_id)

    def has_pending_turn(self) -> bool:
        """Check if there's a turn waiting for response"""
        return self.active_turn_id is not None

    def should_advance_business_state(self, turn: TurnContext) -> bool:
        """Determine if business state should advance based on turn outcome"""
        # Only completed turns should advance business state
        # Cancelled, failed, or pending turns should not
        return turn.status == TurnStatus.COMPLETED

    def create_business_transition(self, plan: TurnPlan, turn: TurnContext) -> Optional[BusinessTransition]:
        """Create business transition if turn completed successfully"""
        if not self.should_advance_business_state(turn):
            return None

        transition = BusinessTransition(
            new_stage=plan.stage_after_completion,
            new_question_order=plan.question_order_after_completion,
            new_expected_reply=plan.expected_reply_after_completion,
            advance_main_completed=plan.advance_main_completed,
            new_followups_used=plan.next_followups_used,
            new_clarifies_used=plan.next_clarifies_used,
            is_natural_end=(turn.turn_kind == TurnKind.CLOSING_PROMPT)
        )

        log_interview_event(
            event_name="turn.transition_applied",
            interview_token=self.token,
            source="turn_orchestrator",
            turn_id=str(turn.turn_id),
            stage=transition.new_stage.value,
            question_order=transition.new_question_order,
            details={
                "advance_main": transition.advance_main_completed,
                "is_natural_end": transition.is_natural_end
            }
        )

        return transition

    def get_stats(self) -> dict:
        """Get orchestrator statistics"""
        return {
            "token": self.token,
            "turns_created": self.turns_created,
            "turns_completed": self.turns_completed,
            "turns_cancelled": self.turns_cancelled,
            "turns_failed": self.turns_failed,
            "active_turn_id": self.active_turn_id,
            "last_completed_turn_id": self.last_completed_turn_id,
            "last_cancelled_turn_id": self.last_cancelled_turn_id
        }
