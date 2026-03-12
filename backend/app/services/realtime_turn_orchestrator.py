"""
Realtime Turn Orchestrator
Manages turn lifecycle and business state transitions for realtime interviews.
"""

import json
import time
from dataclasses import dataclass, field
from typing import Optional, Dict, List
from enum import Enum
from ..utils.logger import logger


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

        logger.info(f"TURN_CREATED: {json.dumps(turn.to_log_dict())}")
        return turn

    def bind_response(self, response_id: str) -> Optional[TurnContext]:
        """Bind a response.created event to the active turn"""
        if not self.active_turn_id:
            logger.warning(f"Cannot bind response {response_id}: no active turn")
            return None

        turn = self.turns_by_id.get(self.active_turn_id)
        if not turn:
            logger.error(f"Active turn {self.active_turn_id} not found in turns_by_id")
            return None

        if turn.response_id and turn.response_id != response_id:
            logger.warning(f"Turn {turn.turn_id} already bound to {turn.response_id}, "
                         f"cannot rebind to {response_id}")
            return None

        turn.response_id = response_id
        turn.status = TurnStatus.IN_PROGRESS
        self.response_to_turn[response_id] = turn.turn_id

        # Initialize transcript buffer for this response
        self.transcript_buffers[response_id] = []

        logger.info(f"TURN_RESPONSE_BOUND: turn_id={turn.turn_id}, response_id={response_id}")
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
            logger.warning(f"Cannot complete: response {response_id} not bound to any turn")
            return None

        turn = self.turns_by_id.get(turn_id)
        if not turn:
            logger.error(f"Turn {turn_id} not found")
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

        logger.info(f"TURN_COMPLETED: {json.dumps(log_data)}")
        return turn

    def cancel_turn(self, response_id: str, reason: str) -> Optional[TurnContext]:
        """Mark a turn as cancelled"""
        turn_id = self.response_to_turn.get(response_id)
        if not turn_id:
            logger.warning(f"Cannot cancel: response {response_id} not bound to any turn")
            return None

        turn = self.turns_by_id.get(turn_id)
        if not turn:
            logger.error(f"Turn {turn_id} not found")
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

        logger.info(f"TURN_CANCELLED: {json.dumps(turn.to_log_dict())}")
        return turn

    def fail_turn(self, response_id: str, error_code: str, error_message: str) -> Optional[TurnContext]:
        """Mark a turn as failed"""
        turn_id = self.response_to_turn.get(response_id) if response_id else self.active_turn_id
        if not turn_id:
            logger.warning(f"Cannot fail: no turn associated with response {response_id}")
            return None

        turn = self.turns_by_id.get(turn_id)
        if not turn:
            logger.error(f"Turn {turn_id} not found")
            return None

        turn.status = TurnStatus.FAILED
        turn.error_code = error_code
        turn.error_message = error_message
        turn.completed_ts = time.time()
        self.turns_failed += 1

        # Clear active turn
        if self.active_turn_id == turn_id:
            self.active_turn_id = None

        logger.info(f"TURN_FAILED: {json.dumps(turn.to_log_dict())}")
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
            logger.info(f"TURN_TRANSITION_SKIPPED: turn_id={turn.turn_id}, status={turn.status.value}")
            return None

        transition = BusinessTransition(
            new_stage=plan.stage_after_completion,
            new_question_order=plan.question_order_after_completion,
            new_expected_reply=plan.expected_reply_after_completion,
            advance_main_completed=plan.advance_main_completed,
            new_followups_used=plan.next_followups_used,
            is_natural_end=(turn.turn_kind == TurnKind.CLOSING_PROMPT)
        )

        logger.info(f"TURN_TRANSITION_APPLIED: turn_id={turn.turn_id}, "
                   f"stage={transition.new_stage.value}, "
                   f"question_order={transition.new_question_order}, "
                   f"advance_main={transition.advance_main_completed}")

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