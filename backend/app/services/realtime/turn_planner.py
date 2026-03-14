from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

from ...config import settings
from ..realtime_turn_orchestrator import InterviewStage, TurnKind, TurnPlan
from .state import SessionState


@dataclass
class PlannerDeps:
    get_user_transcript: Callable[[Optional[str]], str]
    get_allowed_actions: Callable[[], set[str]]
    log_event: Callable[[str, dict], None]


class TurnPlanner:
    def __init__(
        self,
        ordered_questions: list[dict[str, Any]],
        state: SessionState,
        deps: PlannerDeps,
    ):
        self.ordered_questions = ordered_questions
        self.state = state
        self.deps = deps

    def get_main_question(self, order: int) -> Optional[dict[str, Any]]:
        if order <= 0 or order > len(self.ordered_questions):
            return None
        return self.ordered_questions[order - 1]

    def build_main_question_instruction(self, order: int) -> str:
        question = self.get_main_question(order)
        if not question:
            return self.build_closing_instruction()
        question_text = question.get("question_text", "").strip()
        reference = (question.get("reference") or "").strip()
        if settings.REALTIME_STRICT_PROMPT_ENABLED:
            return (
                f"[INTERVIEW_STAGE] qa_main\n"
                f"[QUESTION_ID] {order}\n"
                f"[QUESTION] {question_text}\n"
                f"[REFERENCE] {reference if reference else '开放题'}\n"
                f"[ALLOWED_ACTION] ask_only\n"
                f"[INSTRUCTION] 你必须且仅能提出上述主问题。提问时请先说明'主问题第{order}题'。禁止解释、禁止闲聊、禁止引入新话题。"
            )
        reference_hint = f"参考方向：{reference}。" if reference else "这是一道开放题。"
        return (
            f"现在进入第 {order}/{self.state.main_count_target} 个主问题。"
            f"你必须先明确提出这道主问题：{question_text}。{reference_hint}"
            f"提问时请先说明'主问题第{order}题'。"
        )

    def build_followup_instruction(self, order: int) -> str:
        question = self.get_main_question(order)
        question_text = (question or {}).get("question_text", "").strip()
        if settings.REALTIME_STRICT_PROMPT_ENABLED:
            return (
                f"[INTERVIEW_STAGE] qa_followup\n"
                f"[QUESTION_ID] {order}\n"
                f"[CONTEXT] 围绕主问题：{question_text}\n"
                f"[ALLOWED_ACTION] followup_only\n"
                f"[INSTRUCTION] 请针对候选人刚才的回答做一个极简追问。追问必须聚焦该主问题关键遗漏点。禁止切换话题。"
            )
        return f"请围绕第 {order} 题进行一次简短追问：{question_text}。"

    def build_closing_instruction(self) -> str:
        if settings.REALTIME_STRICT_PROMPT_ENABLED:
            return (
                "[INTERVIEW_STAGE] closing\n"
                "[INSTRUCTION] 所有主问题已完成。请立即礼貌结束面试。禁止提出任何新问题。\n"
                "[REQUIRED_TEXT] 「本次面试到这里就结束了。您可以手动点击'结束面试'按钮，系统也会在稍后自动为您提交。感谢您的参与！」"
            )
        return "所有主问题已完成。请礼貌结束面试。"

    def build_hr_redirect_instruction(self) -> str:
        if settings.REALTIME_STRICT_PROMPT_ENABLED:
            return (
                "[INTERVIEW_STAGE] qa_redirect\n"
                "[INSTRUCTION] 候选人提出 HR 相关问题。请一句话告知后续由 HR 处理，然后立即回到当前面试问题。"
            )
        return "请简短回答候选人的流程问题并回到当前面试题。"

    def legacy_plan(self) -> Optional[TurnPlan]:
        elapsed = time.time() - self.state.interview_start_ts
        elapsed_ratio = elapsed / self.state.time_budget_sec if self.state.time_budget_sec > 0 else 0
        if elapsed >= self.state.time_budget_sec and not self.state.overtime_mode:
            self.state.overtime_mode = True
            self.deps.log_event("INTERVIEW_OVERTIME_ENTERED", {"elapsed_seconds": round(elapsed, 1)})

        if self.state.overtime_mode:
            return TurnPlan(
                turn_kind=TurnKind.CLOSING_PROMPT,
                stage_after_completion=InterviewStage.CLOSING,
                question_order_after_completion=self.state.current_main_question_order,
                expected_reply_after_completion=None,
                control_instruction=self.build_closing_instruction(),
                advance_main_completed=False,
                next_followups_used=0,
                next_clarifies_used=0,
            )

        if self.state.current_stage == InterviewStage.INTRO:
            if self.state.main_count_target <= 0:
                return TurnPlan(
                    turn_kind=TurnKind.CLOSING_PROMPT,
                    stage_after_completion=InterviewStage.CLOSING,
                    question_order_after_completion=0,
                    expected_reply_after_completion=None,
                    control_instruction=self.build_closing_instruction(),
                    advance_main_completed=False,
                    next_followups_used=0,
                    next_clarifies_used=0,
                )
            return TurnPlan(
                turn_kind=TurnKind.MAIN_PROMPT,
                stage_after_completion=InterviewStage.QA,
                question_order_after_completion=1,
                expected_reply_after_completion="main",
                control_instruction=self.build_main_question_instruction(1),
                advance_main_completed=False,
                next_followups_used=0,
                next_clarifies_used=0,
            )

        if self.state.current_stage == InterviewStage.QA:
            advance_main = self.state.expected_candidate_reply_for == "main"
            next_completed = self.state.main_questions_completed + (1 if advance_main else 0)
            can_followup = (
                advance_main and
                self.state.followups_used_for_current < self.state.followup_limit and
                self.state.current_main_question_order > 0 and
                self.state.expected_duration > 0 and
                elapsed_ratio <= 0.95
            )
            if can_followup:
                return TurnPlan(
                    turn_kind=TurnKind.FOLLOWUP_PROMPT,
                    stage_after_completion=InterviewStage.QA,
                    question_order_after_completion=self.state.current_main_question_order,
                    expected_reply_after_completion="followup",
                    control_instruction=self.build_followup_instruction(self.state.current_main_question_order),
                    advance_main_completed=True,
                    next_followups_used=self.state.followups_used_for_current + 1,
                    next_clarifies_used=self.state.clarifies_used_for_current,
                )

            if next_completed >= self.state.main_count_target:
                if advance_main:
                    transcript = self.deps.get_user_transcript(self.state.current_input_item_id)
                    cleaned = re.sub(r"[，。！？；、,.!?;:\s（）()]+", "", transcript or "")
                    confirm_words = [w.strip() for w in settings.REALTIME_MAIN_ANSWER_CONFIRM_WORDS.split(",") if w.strip()]
                    if len(cleaned) < settings.REALTIME_MIN_MAIN_ANSWER_CHARS or cleaned in confirm_words:
                        question = self.get_main_question(self.state.current_main_question_order) or {}
                        return TurnPlan(
                            turn_kind=TurnKind.REASK_PROMPT,
                            stage_after_completion=InterviewStage.QA,
                            question_order_after_completion=self.state.current_main_question_order,
                            expected_reply_after_completion="main",
                            control_instruction=(
                                "[INTERVIEW_STAGE] qa_main_retry\n"
                                f"[INSTRUCTION] 刚才回答较简短。请围绕第{self.state.current_main_question_order}题补充：\n"
                                f"{question.get('question_text', '').strip()}"
                            ),
                            advance_main_completed=False,
                            next_followups_used=self.state.followups_used_for_current,
                            next_clarifies_used=self.state.clarifies_used_for_current,
                        )
                return TurnPlan(
                    turn_kind=TurnKind.CLOSING_PROMPT,
                    stage_after_completion=InterviewStage.CLOSING,
                    question_order_after_completion=self.state.current_main_question_order,
                    expected_reply_after_completion=None,
                    control_instruction=self.build_closing_instruction(),
                    advance_main_completed=advance_main,
                    next_followups_used=0,
                    next_clarifies_used=0,
                )

            if self.state.expected_candidate_reply_for == "followup" or advance_main:
                next_order = next_completed + 1
                return TurnPlan(
                    turn_kind=TurnKind.MAIN_PROMPT,
                    stage_after_completion=InterviewStage.QA,
                    question_order_after_completion=next_order,
                    expected_reply_after_completion="main",
                    control_instruction=self.build_main_question_instruction(next_order),
                    advance_main_completed=advance_main,
                    next_followups_used=0,
                    next_clarifies_used=0,
                )

        if self.state.current_stage == InterviewStage.CLOSING:
            return TurnPlan(
                turn_kind=TurnKind.CLOSING_PROMPT,
                stage_after_completion=InterviewStage.CLOSING,
                question_order_after_completion=self.state.current_main_question_order,
                expected_reply_after_completion=None,
                control_instruction=self.build_closing_instruction(),
                advance_main_completed=False,
                next_followups_used=0,
                next_clarifies_used=0,
            )
        return None

    def build_decision_context(self, latest_candidate_utterance: str) -> dict[str, Any]:
        current_question = self.get_main_question(self.state.current_main_question_order) if self.state.current_main_question_order > 0 else None
        history_turns = max(settings.REALTIME_DECISION_HISTORY_TURNS, 1)
        recent_pairs = self.state.recent_dialogue_turns[-(history_turns * 2):]
        recent_summary = [
            f"{item.get('role', 'Unknown')}: {item.get('text', '')}"
            for item in recent_pairs
            if item.get("text")
        ]
        remaining = max(self.state.main_count_target - self.state.main_questions_completed, 0)
        return {
            "stage": self.state.current_stage.value,
            "question_order": self.state.current_main_question_order,
            "question_text": (current_question or {}).get("question_text", ""),
            "expected_reply_for": self.state.expected_candidate_reply_for,
            "latest_candidate_utterance": latest_candidate_utterance,
            "recent_dialogue_summary": "\n".join(recent_summary),
            "main_questions_completed": self.state.main_questions_completed,
            "main_count_target": self.state.main_count_target,
            "remaining_main_questions": remaining,
            "can_finish_now": remaining <= 0,
            "followups_used_for_current": self.state.followups_used_for_current,
            "followup_limit": self.state.followup_limit,
            "clarifies_used_for_current": self.state.clarifies_used_for_current,
            "clarify_limit": self.state.clarify_limit,
            "allowed_actions": sorted(self.deps.get_allowed_actions()),
        }

    def map_decision_to_plan(self, decision: dict[str, Any]) -> Optional[TurnPlan]:
        action = decision.get("action")
        reason = str(decision.get("reason") or "").strip()
        reason_suffix = f"（决策原因：{reason}）" if reason else ""

        if action == "clarify":
            if self.state.clarifies_used_for_current >= max(self.state.clarify_limit, 0):
                action = "next_question"
            else:
                question = self.get_main_question(self.state.current_main_question_order) or {}
                return TurnPlan(
                    turn_kind=TurnKind.REASK_PROMPT,
                    stage_after_completion=self.state.current_stage,
                    question_order_after_completion=self.state.current_main_question_order,
                    expected_reply_after_completion="main",
                    control_instruction=(
                        "[INTERVIEW_STAGE] qa_clarify\n"
                        f"[INSTRUCTION] 候选人表示未理解。请重新解释并重述第{self.state.current_main_question_order}题："
                        f"{question.get('question_text', '').strip()}。{reason_suffix}"
                    ),
                    advance_main_completed=False,
                    next_followups_used=self.state.followups_used_for_current,
                    next_clarifies_used=self.state.clarifies_used_for_current + 1,
                )

        if action == "followup" and self.state.current_main_question_order > 0:
            if self.state.followups_used_for_current >= max(self.state.followup_limit, 0):
                action = "next_question"
            else:
                return TurnPlan(
                    turn_kind=TurnKind.FOLLOWUP_PROMPT,
                    stage_after_completion=InterviewStage.QA,
                    question_order_after_completion=self.state.current_main_question_order,
                    expected_reply_after_completion="followup",
                    control_instruction=f"{self.build_followup_instruction(self.state.current_main_question_order)}{reason_suffix}",
                    advance_main_completed=(self.state.expected_candidate_reply_for == "main"),
                    next_followups_used=self.state.followups_used_for_current + 1,
                    next_clarifies_used=self.state.clarifies_used_for_current,
                )

        if action == "followup" and self.state.current_main_question_order <= 0:
            action = "next_question"

        if action == "finish_interview":
            if self.state.main_questions_completed < self.state.main_count_target:
                next_order = min(self.state.main_questions_completed + 1, self.state.main_count_target)
                return TurnPlan(
                    turn_kind=TurnKind.MAIN_PROMPT,
                    stage_after_completion=InterviewStage.QA,
                    question_order_after_completion=next_order,
                    expected_reply_after_completion="main",
                    control_instruction=f"{self.build_main_question_instruction(next_order)}{reason_suffix}",
                    advance_main_completed=False,
                    next_followups_used=0,
                    next_clarifies_used=0,
                )
            return TurnPlan(
                turn_kind=TurnKind.CLOSING_PROMPT,
                stage_after_completion=InterviewStage.CLOSING,
                question_order_after_completion=self.state.current_main_question_order,
                expected_reply_after_completion=None,
                control_instruction=self.build_closing_instruction(),
                advance_main_completed=False,
                next_followups_used=0,
                next_clarifies_used=0,
            )

        if action == "next_question":
            advance_main = (self.state.expected_candidate_reply_for == "main")
            next_completed = self.state.main_questions_completed + (1 if advance_main else 0)
            if self.state.current_stage == InterviewStage.INTRO:
                return TurnPlan(
                    turn_kind=TurnKind.MAIN_PROMPT,
                    stage_after_completion=InterviewStage.QA,
                    question_order_after_completion=1,
                    expected_reply_after_completion="main",
                    control_instruction=f"{self.build_main_question_instruction(1)}{reason_suffix}",
                    advance_main_completed=False,
                    next_followups_used=0,
                    next_clarifies_used=0,
                )
            if next_completed >= self.state.main_count_target:
                return TurnPlan(
                    turn_kind=TurnKind.CLOSING_PROMPT,
                    stage_after_completion=InterviewStage.CLOSING,
                    question_order_after_completion=self.state.current_main_question_order,
                    expected_reply_after_completion=None,
                    control_instruction=self.build_closing_instruction(),
                    advance_main_completed=advance_main,
                    next_followups_used=0,
                    next_clarifies_used=0,
                )
            next_order = next_completed + 1
            return TurnPlan(
                turn_kind=TurnKind.MAIN_PROMPT,
                stage_after_completion=InterviewStage.QA,
                question_order_after_completion=next_order,
                expected_reply_after_completion="main",
                control_instruction=f"{self.build_main_question_instruction(next_order)}{reason_suffix}",
                advance_main_completed=advance_main,
                next_followups_used=0,
                next_clarifies_used=0,
            )
        return None
