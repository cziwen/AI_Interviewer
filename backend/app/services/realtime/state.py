from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from ..realtime_turn_orchestrator import InterviewStage, TurnPlan


class PipelineStage(str, Enum):
    IDLE = "idle"
    AUDIO_COLLECTING = "audio_collecting"
    COMMITTED = "committed"
    TRANSCRIBED = "transcribed"
    DECIDED = "decided"
    RESPONDING = "responding"


@dataclass
class SessionState:
    interview_start_ts: float
    time_budget_sec: float
    main_count_target: int
    followup_limit: int
    clarify_limit: int
    expected_duration: int

    current_stage: InterviewStage = InterviewStage.INTRO
    expected_candidate_reply_for: Optional[str] = "intro"
    main_questions_completed: int = 0
    current_main_question_order: int = 0
    followups_used_for_current: int = 0
    clarifies_used_for_current: int = 0
    overtime_mode: bool = False
    overtime_closing_sent: bool = False
    candidate_speaking: bool = False
    natural_end_sent: bool = False

    current_input_item_id: Optional[str] = None
    commit_pending: bool = False
    last_committed_item_id: Optional[str] = None
    has_uncommitted_audio: bool = False
    pending_plan: Optional[TurnPlan] = None

    pipeline_stage: PipelineStage = PipelineStage.IDLE
    decision_pending: bool = False
    active_segment_id: Optional[str] = None
    recent_dialogue_turns: list[dict[str, str]] = field(default_factory=list)

    def advance_main_if_needed(self, should_advance: bool) -> None:
        if should_advance:
            self.main_questions_completed += 1
