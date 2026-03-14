from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Optional

import openai

from ...config import settings
from ..realtime_turn_orchestrator import InterviewStage, TurnKind

DECISION_ACTIONS = {
    "followup",
    "next_question",
    "clarify",
    "finish_interview",
}


def clamp_text(raw: str, max_chars: int) -> str:
    text = (raw or "").strip()
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[:max_chars]


def parse_and_validate_decision(
    raw_text: str,
    allowed_actions: Optional[set[str]] = None,
) -> tuple[Optional[dict], Optional[str]]:
    text = (raw_text or "").strip()
    if not text:
        return None, "empty_output"
    try:
        payload = json.loads(text)
    except Exception:
        return None, "invalid_json"

    if not isinstance(payload, dict):
        return None, "invalid_json_shape"

    action = str(payload.get("action") or "").strip()
    reason = str(payload.get("reason") or "").strip()
    if action not in DECISION_ACTIONS:
        return None, "invalid_action"
    if allowed_actions is not None and action not in allowed_actions:
        return None, "action_not_allowed"
    if not reason:
        return None, "missing_reason"

    return {"action": action, "reason": reason}, None


def decision_action_to_turn_kind(action: str) -> Optional[TurnKind]:
    mapping = {
        "followup": TurnKind.FOLLOWUP_PROMPT,
        "next_question": TurnKind.MAIN_PROMPT,
        "clarify": TurnKind.REASK_PROMPT,
        "finish_interview": TurnKind.CLOSING_PROMPT,
    }
    return mapping.get(action)


class DecisionEngine:
    def __init__(self, api_key: Optional[str]):
        self._client = openai.AsyncOpenAI(api_key=api_key) if api_key else None

    async def call_decision_llm(self, context: dict[str, Any]) -> tuple[Optional[dict], Optional[str], int]:
        if not self._client:
            return None, "api_key_missing", 0

        timeout_sec = max(settings.REALTIME_DECISION_TIMEOUT_MS, 200) / 1000.0
        start_ts = time.time()
        system_prompt = (
            "你是面试流程控制器决策层。"
            "你只负责判断下一步动作，不要生成面试话术。"
            "必须只输出 JSON 对象，格式为 {\"action\":...,\"reason\":...}。"
            "action 必须从 allowed_actions 中选择。"
            "当 remaining_main_questions > 0 时，禁止选择 finish_interview。"
        )
        user_prompt = (
            "当前面试状态如下：\n"
            f"- 当前阶段: {context.get('stage')}\n"
            f"- 当前问题序号: {context.get('question_order')}\n"
            f"- 当前问题: {context.get('question_text')}\n"
            f"- 期望候选人回复类型: {context.get('expected_reply_for')}\n"
            f"- 已完成主问题数: {context.get('main_questions_completed')}\n"
            f"- 主问题目标数: {context.get('main_count_target')}\n"
            f"- 剩余主问题数: {context.get('remaining_main_questions')}\n"
            f"- 当前是否允许结束: {context.get('can_finish_now')}\n"
            f"- 当前允许动作: {', '.join(context.get('allowed_actions') or [])}\n"
            f"- 候选人最新发言: {context.get('latest_candidate_utterance')}\n"
            f"- 最近对话摘要:\n{context.get('recent_dialogue_summary')}\n"
            "请根据上述信息选择最合适动作。"
        )
        try:
            response = await asyncio.wait_for(
                self._client.chat.completions.create(
                    model=settings.REALTIME_DECISION_MODEL,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0,
                ),
                timeout=timeout_sec,
            )
            latency_ms = int((time.time() - start_ts) * 1000)
            raw_text = ((response.choices[0].message.content if response.choices else "") or "").strip()
            decision, parse_error = parse_and_validate_decision(
                raw_text,
                allowed_actions=set(context.get("allowed_actions") or []),
            )
            if parse_error:
                return None, parse_error, latency_ms
            return decision, None, latency_ms
        except asyncio.TimeoutError:
            return None, "timeout", int((time.time() - start_ts) * 1000)
        except Exception:
            return None, "api_error", int((time.time() - start_ts) * 1000)

    @staticmethod
    def get_allowed_actions(
        current_stage: InterviewStage,
        main_count_target: int,
        main_questions_completed: int,
        current_main_question_order: int,
        followups_used_for_current: int,
        followup_limit: int,
        clarifies_used_for_current: int,
        clarify_limit: int,
    ) -> set[str]:
        actions: set[str] = set()
        can_finish_now = (
            main_count_target <= 0 or
            main_questions_completed >= main_count_target
        )
        if clarifies_used_for_current < max(clarify_limit, 0):
            actions.add("clarify")
        if current_stage == InterviewStage.INTRO:
            actions.add("next_question")
        elif current_stage == InterviewStage.QA:
            actions.add("next_question")
            if (
                current_main_question_order > 0 and
                followups_used_for_current < max(followup_limit, 0)
            ):
                actions.add("followup")
        elif current_stage == InterviewStage.CLOSING and can_finish_now:
            actions.add("finish_interview")

        if can_finish_now:
            actions.add("finish_interview")
        return actions
