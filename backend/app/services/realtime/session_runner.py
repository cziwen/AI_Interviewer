from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import time
from typing import Any, Optional

import websockets
from fastapi import WebSocket

from ...config import settings
from ...models.interview import Interview
from ...models.job_profile import JobProfile
from ...utils.logger import log_dialogue_line, log_interview_event
from ...utils.usage_tracker import InterviewUsageTracker
from ..realtime_turn_orchestrator import (
    BusinessTransition,
    InterviewStage,
    RealtimeTurnOrchestrator,
    TurnKind,
    TurnPlan,
    TurnStatus,
)
from .audio_pipeline import AudioPipeline
from .decision_engine import DecisionEngine, clamp_text
from .persistence import persist_audio_and_answer_sync
from .state import PipelineStage, SessionState
from .transcript_store import TranscriptStore
from .turn_planner import PlannerDeps, TurnPlanner

OPENAI_REALTIME_URL = "wss://api.openai.com/v1/realtime?model=gpt-realtime-mini"


class RealtimeSessionRunner:
    def __init__(self, websocket: WebSocket, token: str, interview: Interview, job_profile: Optional[JobProfile]):
        self.websocket = websocket
        self.token = token
        self.interview = interview
        self.job_profile = job_profile
        self.openai_ws = None
        self.init_event: dict[str, Any] = {}
        self.pipeline_lock = asyncio.Lock()
        self.usage_tracker = InterviewUsageTracker(interview_id=interview.id, interview_token=token)
        self.orchestrator = RealtimeTurnOrchestrator(
            token=token,
            candidate_name=interview.name or "候选人",
            position=interview.position or "基础岗位",
        )
        self.decision_engine = DecisionEngine(settings.OPENAI_API_KEY)
        self.transcript_store = TranscriptStore(self.orchestrator)

        self.jd_info = "暂无详细岗位要求"
        self.main_question_count = 3
        self.followup_limit = 1
        self.clarify_limit = 1
        self.expected_duration = 10
        self.ordered_questions: list[dict[str, Any]] = []
        self.state: Optional[SessionState] = None
        self.audio_pipeline: Optional[AudioPipeline] = None

    async def run(self) -> None:
        await self.websocket.accept()
        self._load_job_profile()
        self._init_runtime_state()
        await self._connect_openai()
        await self._send_session_update()
        await self._send_intro_turn()
        await asyncio.gather(self._relay_client_to_openai(), self._relay_openai_to_client())

    def _load_job_profile(self) -> None:
        if self.job_profile:
            jd_data = self.job_profile.jd_data
            self.main_question_count = jd_data.get("main_question_count", 3)
            self.followup_limit = jd_data.get("followup_limit_per_question", 1)
            self.expected_duration = jd_data.get("expected_duration_minutes", 10)
            jd_summary = []
            if "responsibilities" in jd_data:
                jd_summary.append(f"岗位职责: {jd_data['responsibilities']}")
            if "requirements" in jd_data:
                jd_summary.append(f"任职要求: {jd_data['requirements']}")
            if "plus" in jd_data:
                jd_summary.append(f"加分项: {jd_data['plus']}")
            if jd_summary:
                self.jd_info = "\n".join(jd_summary)

        self.ordered_questions = sorted(
            self.interview.question_set or [],
            key=lambda q: q.get("order_index", 0),
        )

    def _init_runtime_state(self) -> None:
        main_count_target = min(self.main_question_count, len(self.ordered_questions))
        state = SessionState(
            interview_start_ts=time.time(),
            time_budget_sec=self.expected_duration * 60,
            main_count_target=main_count_target,
            followup_limit=self.followup_limit,
            clarify_limit=self.clarify_limit,
            expected_duration=self.expected_duration,
        )
        self.state = state
        self.audio_pipeline = AudioPipeline(state)

    async def _connect_openai(self) -> None:
        log_interview_event(
            event_name="openai.connecting",
            interview_id=self.interview.id,
            interview_token=self.token,
            source="api.realtime",
        )
        self.openai_ws = await websockets.connect(
            OPENAI_REALTIME_URL,
            additional_headers={
                "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                "OpenAI-Beta": "realtime=v1",
            },
        )
        log_interview_event(
            event_name="openai.connected",
            interview_id=self.interview.id,
            interview_token=self.token,
            source="api.realtime",
        )

    async def _send_session_update(self) -> None:
        formatted_questions = []
        for question in self.interview.question_set:
            ref = question.get("reference")
            ref_text = f"（参考方向/要点：{ref}）" if ref else "（开放题，无固定参考方向）"
            formatted_questions.append(f"题目 {question['order_index']}：{question['question_text']} {ref_text}")
        questions_str = "\n".join(formatted_questions)

        self.init_event = {
            "type": "session.update",
            "session": {
                "instructions": f"""
你是一名专业的 AI 面试官。你正在面试候选人 {self.interview.name or '先生/女士'}，岗位是 {self.interview.position or '基础岗位'}。

岗位背景信息 (JD)：
{self.jd_info}

本次面试流程：
1. 自我介绍 (intro)。
2. 主问题问答 (qa)。
3. 自然结束 (closing)。

本次面试规则与参数：
1. 主问题数量：{self.main_question_count}
2. 追问限额：每题最多 {self.followup_limit} 次
3. 预期时长：{self.expected_duration} 分钟
4. 每次只问一个问题
5. 请使用中文

题目列表与参考方向：
{questions_str}
""",
                "voice": "alloy",
                "modalities": ["text", "audio"],
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                "input_audio_transcription": {"model": "whisper-1"},
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.5,
                    "prefix_padding_ms": 300,
                    "silence_duration_ms": 1200,
                    "create_response": False,
                },
            },
        }
        await self.openai_ws.send(json.dumps(self.init_event))
        await asyncio.sleep(0.3)

    def _build_planner(self) -> TurnPlanner:
        deps = PlannerDeps(
            get_user_transcript=lambda item_id: self.transcript_store.get_user_transcript(item_id),
            get_allowed_actions=self._get_allowed_actions,
            log_event=self._log_turn_state,
        )
        return TurnPlanner(self.ordered_questions, self.state, deps)

    def _get_allowed_actions(self) -> set[str]:
        return self.decision_engine.get_allowed_actions(
            self.state.current_stage,
            self.state.main_count_target,
            self.state.main_questions_completed,
            self.state.current_main_question_order,
            self.state.followups_used_for_current,
            self.state.followup_limit,
            self.state.clarifies_used_for_current,
            self.state.clarify_limit,
        )

    def _log_turn_state(self, event: str, extra: Optional[dict] = None, **kwargs: Any) -> None:
        active_turn = self.orchestrator.get_active_turn()
        log_interview_event(
            event_name=event,
            interview_id=self.interview.id,
            interview_token=self.token,
            source="turn_orchestrator",
            stage=self.state.current_stage.value,
            turn_id=active_turn.turn_id if active_turn else None,
            details=extra or {},
            question_order=self.state.current_main_question_order,
            main_completed_count=self.state.main_questions_completed,
            followups_used=self.state.followups_used_for_current,
            expected_reply=self.state.expected_candidate_reply_for,
            overtime_mode=self.state.overtime_mode,
            turn_status=active_turn.status.value if active_turn else None,
            **kwargs,
        )

    async def _send_intro_turn(self) -> None:
        first_plan = TurnPlan(
            turn_kind=TurnKind.INTRO_PROMPT,
            stage_after_completion=InterviewStage.INTRO,
            question_order_after_completion=0,
            expected_reply_after_completion="intro",
            control_instruction=(
                "[INTERVIEW_STAGE] intro\n"
                "[INSTRUCTION] 请开始面试，向候选人问好并请他进行简短的自我介绍。"
            ),
            advance_main_completed=False,
            next_followups_used=0,
        )
        await self._send_response_create_with_turn(first_plan)

    def _add_dialogue_turn(self, role: str, text: str) -> None:
        snippet = clamp_text(text, 500)
        if not snippet:
            return
        self.state.recent_dialogue_turns.append({"role": role, "text": snippet})
        max_entries = max(settings.REALTIME_DECISION_HISTORY_TURNS * 2, 4)
        if len(self.state.recent_dialogue_turns) > max_entries:
            del self.state.recent_dialogue_turns[:-max_entries]

    async def _commit_input_audio_once(self, reason: str, item_id: Optional[str] = None) -> bool:
        resolved_item_id = item_id or self.state.current_input_item_id
        if not self.state.has_uncommitted_audio:
            self._log_turn_state("COMMIT_SKIPPED_NO_AUDIO", {"reason": reason, "item_id": resolved_item_id})
            return False
        if self.state.commit_pending:
            return False
        if resolved_item_id and resolved_item_id == self.state.last_committed_item_id:
            return False

        await self.openai_ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
        self.state.commit_pending = True
        return True

    async def _wait_and_log_transcript(self, item_id: Optional[str]) -> str:
        transcript, waited_ms = await self.transcript_store.wait_for_user_transcript(item_id)
        if transcript:
            self._log_turn_state(
                "pipeline.transcribed",
                {"item_id": item_id, "waited_ms": waited_ms, "chars": len(transcript)},
            )
            self.state.pipeline_stage = PipelineStage.TRANSCRIBED
            return transcript
        self._log_turn_state("pipeline.transcription_timeout", {"item_id": item_id, "waited_ms": waited_ms})
        return ""

    async def _decide_next_turn(self) -> Optional[TurnPlan]:
        planner = self._build_planner()
        fallback_plan = planner.legacy_plan()
        latest_utterance = self.transcript_store.get_user_transcript(self.state.current_input_item_id)
        if not latest_utterance:
            for item in reversed(self.state.recent_dialogue_turns):
                if item.get("role") == "Candidate" and item.get("text"):
                    latest_utterance = item["text"]
                    break

        if not settings.REALTIME_DECISION_LAYER_ENABLED:
            return fallback_plan
        context = planner.build_decision_context(latest_utterance or "")
        self._log_turn_state("decision_layer.requested", {"allowed_actions": context.get("allowed_actions", [])})
        decision, error_reason, latency_ms = await self.decision_engine.call_decision_llm(context)
        if error_reason or not decision:
            self._log_turn_state("decision_layer.fallback", {"reason": error_reason or "unknown", "latency_ms": latency_ms})
            return fallback_plan
        plan = planner.map_decision_to_plan(decision)
        if not plan:
            return fallback_plan
        self._log_turn_state("decision_layer.succeeded", {"action": decision.get("action"), "latency_ms": latency_ms})
        self.state.pipeline_stage = PipelineStage.DECIDED
        return plan

    async def _send_response_create_with_turn(self, plan: TurnPlan) -> None:
        if self.orchestrator.has_pending_turn():
            self._log_turn_state("AI_RESPONSE_CREATE_SKIPPED", {"reason": "pending_turn"})
            return
        turn = self.orchestrator.create_turn(
            plan=plan,
            current_stage=self.state.current_stage,
            expected_reply_before=self.state.expected_candidate_reply_for,
            question_order=self.state.current_main_question_order,
        )
        self.state.pending_plan = plan
        await self.openai_ws.send(
            json.dumps(
                {
                    "type": "response.create",
                    "response": {"instructions": plan.control_instruction},
                }
            )
        )
        self._log_turn_state("pipeline.responding", {"turn_id": turn.turn_id, "turn_kind": turn.turn_kind.value})
        self.state.pipeline_stage = PipelineStage.RESPONDING

    def _apply_business_transition(self, transition: Optional[BusinessTransition]) -> None:
        if not transition:
            return
        self.state.current_stage = transition.new_stage
        self.state.current_main_question_order = transition.new_question_order
        self.state.expected_candidate_reply_for = transition.new_expected_reply
        if transition.advance_main_completed:
            self.state.main_questions_completed += 1
        self.state.followups_used_for_current = transition.new_followups_used
        self.state.clarifies_used_for_current = transition.new_clarifies_used
        if transition.is_natural_end and not self.state.natural_end_sent:
            asyncio.create_task(self.websocket.send_text(json.dumps({"type": "interview.natural_end"})))
            self.state.natural_end_sent = True
        self._log_turn_state("pipeline.completed", {"stage": self.state.current_stage.value})

    async def _finalize_candidate_segment(self, trigger: str, segment_pcm: Optional[bytes], item_id: Optional[str]) -> None:
        async with self.pipeline_lock:
            if self.state.decision_pending:
                self._log_turn_state("pipeline.skip_duplicate_finalize", {"trigger": trigger})
                return
            self.state.decision_pending = True
            try:
                self._log_turn_state("pipeline.segment_started", {"trigger": trigger, "item_id": item_id})
                await self._commit_input_audio_once(f"linear_finalize:{trigger}", item_id)
                self.state.pipeline_stage = PipelineStage.COMMITTED
                self._log_turn_state("pipeline.committed", {"item_id": item_id})

                if segment_pcm:
                    answer_idx = 0
                    if self.state.expected_candidate_reply_for in ("main", "followup") and self.state.current_main_question_order > 0:
                        answer_idx = self.state.current_main_question_order
                    transcript = self.transcript_store.get_user_transcript(item_id)
                    try:
                        file_path = await asyncio.to_thread(
                            persist_audio_and_answer_sync,
                            segment_pcm,
                            self.interview.id,
                            self.token,
                            answer_idx,
                            transcript,
                        )
                        log_interview_event(
                            event_name="vad.segment_saved",
                            interview_id=self.interview.id,
                            interview_token=self.token,
                            source="api.realtime",
                            stage=self.state.current_stage.value,
                            details={"file_path": file_path, "question_index": answer_idx, "duration_ms": len(segment_pcm) / 48},
                        )
                    except Exception as exc:
                        log_interview_event(
                            event_name="answer.persist_async_failed",
                            interview_id=self.interview.id,
                            interview_token=self.token,
                            source="api.realtime",
                            level=logging.ERROR,
                            outcome="failed",
                            error_message=str(exc),
                        )
                    self.usage_tracker.add_audio_usage(
                        model_name="gpt-realtime-mini",
                        input_seconds=len(segment_pcm) / 48000.0,
                    )

                await self._wait_and_log_transcript(item_id)
                plan = await self._decide_next_turn()
                if plan:
                    await self._send_response_create_with_turn(plan)
            finally:
                self.state.decision_pending = False
                if self.state.pipeline_stage != PipelineStage.RESPONDING:
                    self.state.pipeline_stage = PipelineStage.IDLE

    async def _relay_client_to_openai(self) -> None:
        try:
            async for message in self.websocket.iter_text():
                data = json.loads(message)
                msg_type = data.get("type")
                if msg_type == "audio":
                    audio_data = data["audio"]
                    self.audio_pipeline.on_client_audio(audio_data)
                    await self.openai_ws.send(json.dumps({"type": "input_audio_buffer.append", "audio": audio_data}))
                elif msg_type == "end_turn":
                    await self._finalize_candidate_segment(
                        trigger="client_end_turn",
                        segment_pcm=None,
                        item_id=self.state.current_input_item_id,
                    )
                elif msg_type == "no_response_timeout":
                    if self.state.current_stage != InterviewStage.CLOSING and not self.state.candidate_speaking:
                        reask_plan = TurnPlan(
                            turn_kind=TurnKind.REASK_PROMPT,
                            stage_after_completion=self.state.current_stage,
                            question_order_after_completion=self.state.current_main_question_order,
                            expected_reply_after_completion=self.state.expected_candidate_reply_for,
                            control_instruction="候选人尚未回答。请简短重复当前问题或礼貌提醒候选人作答，不要换题。",
                            advance_main_completed=False,
                            next_followups_used=self.state.followups_used_for_current,
                            next_clarifies_used=self.state.clarifies_used_for_current,
                        )
                        await self._send_response_create_with_turn(reask_plan)
        except Exception as exc:
            log_interview_event(
                event_name="relay.client_to_openai.error",
                interview_id=self.interview.id,
                interview_token=self.token,
                source="api.realtime",
                level=logging.ERROR,
                outcome="failed",
                error_message=str(exc),
            )

    async def _relay_openai_to_client(self) -> None:
        try:
            async for message in self.openai_ws:
                event = json.loads(message)
                event_type = event.get("type")

                if event_type in ["response.audio.delta", "response.text.delta", "response.audio_transcript.delta"]:
                    if event_type == "response.audio.delta":
                        delta_audio = event.get("delta", "")
                        if delta_audio:
                            pcm_bytes = base64.b64decode(delta_audio)
                            self.usage_tracker.add_audio_usage(
                                model_name="gpt-realtime-mini",
                                output_seconds=len(pcm_bytes) / 48000.0,
                            )
                        modified_event = event.copy()
                        if "delta" in modified_event:
                            modified_event["audio"] = modified_event["delta"]
                        await self.websocket.send_text(json.dumps(modified_event))
                    else:
                        await self.websocket.send_text(json.dumps(event))
                    if event_type == "response.audio_transcript.delta":
                        response_id = event.get("response_id")
                        if response_id:
                            self.orchestrator.append_transcript_delta(response_id, event.get("delta", ""))
                    continue

                if event_type == "response.created":
                    response = event.get("response", {})
                    response_id = response.get("id")
                    if response_id:
                        turn = self.orchestrator.bind_response(response_id)
                        if turn:
                            self._log_turn_state("AI_RESPONSE_CREATED", {"response_id": response_id, "turn_id": turn.turn_id})
                    await self.websocket.send_text(json.dumps(event))
                    continue

                if event_type == "conversation.item.input_audio_transcription.completed":
                    item_id = event.get("item_id")
                    transcript = event.get("transcript", "")
                    if transcript:
                        self.transcript_store.set_user_transcript(item_id, transcript)
                        log_dialogue_line(interview_token=self.token, role="Candidate", text=transcript)
                        self._add_dialogue_turn("Candidate", transcript)
                    continue

                if event_type == "response.done":
                    response = event.get("response", {})
                    response_id = response.get("id")
                    status = response.get("status")
                    status_details = response.get("status_details", {})
                    usage = response.get("usage")
                    if usage:
                        self.usage_tracker.add_text_usage(
                            model_name="gpt-realtime-mini",
                            input_tokens=usage.get("input_tokens", 0),
                            output_tokens=usage.get("output_tokens", 0),
                        )
                    if status == "completed":
                        turn = self.orchestrator.complete_turn(response_id, usage)
                        if turn:
                            if turn.turn_kind == TurnKind.MAIN_PROMPT and turn.status == TurnStatus.COMPLETED:
                                q_order = turn.target_question_order or self.state.current_main_question_order
                                aligned = self._is_main_question_aligned(q_order, turn.transcript)
                                if not aligned and settings.REALTIME_STRICT_PROMPT_ENABLED:
                                    planner = self._build_planner()
                                    reask = TurnPlan(
                                        turn_kind=TurnKind.REASK_PROMPT,
                                        stage_after_completion=self.state.current_stage,
                                        question_order_after_completion=q_order,
                                        expected_reply_after_completion=turn.target_expected_reply or self.state.expected_candidate_reply_for,
                                        control_instruction=(
                                            "[INTERVIEW_STAGE] drift_correction\n"
                                            f"[INSTRUCTION] 刚才跑题了。请重述主问题第{q_order}题："
                                            f"{(planner.get_main_question(q_order) or {}).get('question_text', '').strip()}"
                                        ),
                                        advance_main_completed=False,
                                        next_followups_used=self.state.followups_used_for_current,
                                        next_clarifies_used=self.state.clarifies_used_for_current,
                                    )
                                    await self._send_response_create_with_turn(reask)
                                    self.state.pending_plan = None
                                    continue
                            if self.state.pending_plan and self.orchestrator.should_advance_business_state(turn):
                                transition = self.orchestrator.create_business_transition(self.state.pending_plan, turn)
                                self._apply_business_transition(transition)
                                self.state.pending_plan = None
                            if turn.transcript:
                                log_dialogue_line(interview_token=self.token, role="AI", text=turn.transcript)
                                self._add_dialogue_turn("AI", turn.transcript)
                    elif status == "cancelled":
                        self.orchestrator.cancel_turn(response_id, status_details.get("reason", "unknown"))
                        self.state.pending_plan = None
                    elif status == "failed":
                        error = status_details.get("error", {})
                        self.orchestrator.fail_turn(response_id, error.get("code", "unknown"), error.get("message", ""))
                        self.state.pending_plan = None
                    continue

                if event_type == "error":
                    err = event.get("error", {}) or {}
                    if err.get("code") == "input_audio_buffer_commit_empty":
                        self.state.commit_pending = False
                        self.state.has_uncommitted_audio = False
                    continue

                if event_type == "input_audio_buffer.speech_started":
                    self.audio_pipeline.on_speech_started(event.get("item_id"))
                    log_interview_event(
                        event_name="vad.speech_started",
                        interview_id=self.interview.id,
                        interview_token=self.token,
                        source="api.realtime",
                        stage=self.state.current_stage.value,
                        details={"audio_start_ms": event.get("audio_start_ms", 0)},
                    )
                    continue

                if event_type == "input_audio_buffer.speech_stopped":
                    segment = self.audio_pipeline.on_speech_stopped(event.get("item_id"))
                    log_interview_event(
                        event_name="vad.speech_stopped",
                        interview_id=self.interview.id,
                        interview_token=self.token,
                        source="api.realtime",
                        stage=self.state.current_stage.value,
                        details={"audio_end_ms": event.get("audio_end_ms", 0)},
                    )
                    if segment:
                        await self._finalize_candidate_segment(
                            trigger="vad_speech_stopped",
                            segment_pcm=segment.pcm_data,
                            item_id=segment.item_id,
                        )
                    continue

                if event_type == "input_audio_buffer.committed":
                    self.state.commit_pending = False
                    self.state.has_uncommitted_audio = False
                    committed_item_id = event.get("item_id")
                    if committed_item_id:
                        self.state.last_committed_item_id = committed_item_id
                    continue

                if event_type in ["response.completed", "conversation.item.created", "session.updated", "session.created"]:
                    await self.websocket.send_text(json.dumps(event))
        except Exception as exc:
            log_interview_event(
                event_name="relay.openai_to_client.error",
                interview_id=self.interview.id,
                interview_token=self.token,
                source="api.realtime",
                level=logging.ERROR,
                outcome="failed",
                error_message=str(exc),
            )
        finally:
            if self.openai_ws and not self.openai_ws.closed:
                await self.openai_ws.close()
            self.usage_tracker.log_summary()
            log_interview_event(
                event_name="orchestrator.stats",
                interview_id=self.interview.id,
                interview_token=self.token,
                source="turn_orchestrator",
                details=self.orchestrator.get_stats(),
            )

    def _is_main_question_aligned(self, order: int, assistant_transcript: str) -> bool:
        planner = self._build_planner()
        question = planner.get_main_question(order) or {}
        question_text = (question.get("question_text") or "").strip()
        answer_text = (assistant_transcript or "").strip()
        if not question_text or not answer_text:
            return False
        normalized_q = re.sub(r"\s+", "", question_text)
        normalized_a = re.sub(r"\s+", "", answer_text)
        if normalized_q[:12] and normalized_q[:12] in normalized_a:
            return True
        chunks = [c for c in re.split(r"[，。！？；、,.!?;:\s（）()]+", question_text) if len(c) >= 4]
        matched = [c for c in chunks[:6] if c in normalized_a]
        if len(chunks) >= 2:
            return len(matched) >= 2
        return len(matched) >= 1
