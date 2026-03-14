import json
import base64
import asyncio
import websockets
import wave
import io
from typing import Optional, Any
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy.orm import Session
from ..database import get_db, SessionLocal
from ..models.interview import Interview, InterviewStatus
from ..models.job_profile import JobProfile
from ..models.answer import Answer
from ..config import settings
from ..utils.logger import logger, log_interview_event, log_dialogue_line
from ..utils.usage_tracker import InterviewUsageTracker
from ..services.realtime_turn_orchestrator import (
    RealtimeTurnOrchestrator,
    TurnPlan,
    TurnKind,
    InterviewStage,
    TurnStatus,
    TurnContext,
    BusinessTransition,
)
import os
import secrets
import time
import re
import logging
import openai

router = APIRouter()

# Global registry for active interview tokens to prevent duplicate sessions
active_interview_tokens = set()
active_tokens_lock = asyncio.Lock()

OPENAI_REALTIME_URL = "wss://api.openai.com/v1/realtime?model=gpt-realtime-mini"

# 候选人长时间未回答时，等待多少秒后由 AI 重新提问或提醒
NO_RESPONSE_REASK_SECONDS = 18
TRANSCRIPT_WAIT_MAX_MS = 1200
TRANSCRIPT_WAIT_POLL_MS = 50
DECISION_ACTIONS = {
    "followup",
    "next_question",
    "answer_candidate_question",
    "clarify",
    "finish_interview",
}

def _persist_audio_and_answer_sync(
    pcm_data: bytes, 
    interview_id: int, 
    token: str, 
    answer_question_index: int, 
    transcript: Optional[str]
) -> str:
    """
    Synchronous helper to save audio file and record answer in DB.
    Designed to be run in a separate thread.
    """
    db = SessionLocal()
    try:
        # 1. WAV conversion
        wav_data = pcm16_to_wav(pcm_data)

        # 2. Save to file
        file_name = f"{token}_{answer_question_index}_{secrets.token_hex(4)}.wav"
        file_path = os.path.join(settings.UPLOAD_DIR, file_name)
        with open(file_path, "wb") as f:
            f.write(wav_data)

        # 3. DB record
        db_answer = Answer(
            interview_id=interview_id,
            question_index=answer_question_index,
            audio_url=file_path,
            transcript=transcript
        )
        db.add(db_answer)
        db.commit()
        return file_path
    except Exception as e:
        db.rollback()
        log_interview_event(
            event_name="answer.persist_failed",
            interview_id=interview_id,
            interview_token=token,
            level=logging.ERROR,
            source="api.realtime",
            outcome="failed",
            error_message=str(e),
            details={"question_index": answer_question_index},
        )
        raise
    finally:
        db.close()

def pcm16_to_wav(pcm_data: bytes, sample_rate: int = 24000, channels: int = 1) -> bytes:
    """
    将原始 PCM16 数据封装为 WAV 格式。
    """
    with io.BytesIO() as wav_io:
        with wave.open(wav_io, 'wb') as wav_file:
            wav_file.setnchannels(channels)
            wav_file.setsampwidth(2)  # 16-bit
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm_data)
        return wav_io.getvalue()


def _clamp_text(raw: str, max_chars: int) -> str:
    text = (raw or "").strip()
    if max_chars <= 0:
        return text
    if len(text) <= max_chars:
        return text
    return text[:max_chars]


def _parse_and_validate_decision(
    raw_text: str,
    allowed_actions: Optional[set[str]] = None,
) -> tuple[Optional[dict], Optional[str]]:
    """Validate decision JSON and return (decision, error_reason)."""
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


def _decision_action_to_turn_kind(action: str) -> Optional[TurnKind]:
    mapping = {
        "followup": TurnKind.FOLLOWUP_PROMPT,
        "next_question": TurnKind.MAIN_PROMPT,
        "answer_candidate_question": TurnKind.HR_REDIRECT_PROMPT,
        "clarify": TurnKind.REASK_PROMPT,
        "finish_interview": TurnKind.CLOSING_PROMPT,
    }
    return mapping.get(action)

@router.websocket("/ws/{token}")
async def realtime_interview_endpoint(websocket: WebSocket, token: str, db: Session = Depends(get_db)):
    # 1. Check for duplicate session for this token
    async with active_tokens_lock:
        if token in active_interview_tokens:
            logger.warning(f"Duplicate WebSocket connection attempt for token: {token}. Rejecting.")
            await websocket.close(code=4003, reason="Duplicate session")
            return
        active_interview_tokens.add(token)

    try:
            interview = db.query(Interview).filter(Interview.link_token == token).first()
            if not interview:
                logger.warning(f"WebSocket connection attempt with invalid token: {token}")
                await websocket.close(code=4004)
                return

            await websocket.accept()

            log_interview_event(
                event_name="ws.connected",
                interview_id=interview.id,
                interview_token=token,
                source="api.realtime",
                stage="intro",
                details={
                    "candidate_name": interview.name,
                    "position": interview.position
                }
            )

            # Fetch JobProfile if available to get JD metadata
            jd_info = "暂无详细岗位要求"
            main_question_count = 3
            followup_limit = 1
            expected_duration = 10

            job_profile = db.query(JobProfile).filter(JobProfile.position_name == interview.position).first()
            if job_profile:
                jd_data = job_profile.jd_data
                main_question_count = jd_data.get('main_question_count', 3)
                followup_limit = jd_data.get('followup_limit_per_question', 1)
                expected_duration = jd_data.get('expected_duration_minutes', 10)

                # Create a summary of JD
                jd_summary = []
                if 'responsibilities' in jd_data:
                    jd_summary.append(f"岗位职责: {jd_data['responsibilities']}")
                if 'requirements' in jd_data:
                    jd_summary.append(f"任职要求: {jd_data['requirements']}")
                if 'plus' in jd_data:
                    jd_summary.append(f"加分项: {jd_data['plus']}")

                if jd_summary:
                    jd_info = "\n".join(jd_summary)

            # Initialize Turn Orchestrator
            orchestrator = RealtimeTurnOrchestrator(
                token=token,
                candidate_name=interview.name or '候选人',
                position=interview.position or '基础岗位'
            )

            # Initialize Usage Tracker
            usage_tracker = InterviewUsageTracker(interview_id=interview.id, interview_token=token)
            decision_client = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY) if settings.OPENAI_API_KEY else None

            # Connect to OpenAI Realtime
            headers = {
                "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                "OpenAI-Beta": "realtime=v1"
            }

            log_interview_event(
                event_name="openai.connecting",
                interview_id=interview.id,
                interview_token=token,
                source="api.realtime"
            )
            openai_ws = await websockets.connect(OPENAI_REALTIME_URL, additional_headers=headers)
            log_interview_event(
                event_name="openai.connected",
                interview_id=interview.id,
                interview_token=token,
                source="api.realtime"
            )

            # Format question list with references
            formatted_questions = []
            for q in interview.question_set:
                ref = q.get('reference')
                ref_text = f"（参考方向/要点：{ref}）" if ref else "（开放题，无固定参考方向）"
                formatted_questions.append(f"题目 {q['order_index']}：{q['question_text']} {ref_text}")

            questions_str = "\n".join(formatted_questions)

            # 1. Initialize session with instructions and tools
            init_event = {
                "type": "session.update",
                "session": {
                    "instructions": f"""
你是一名专业的 AI 面试官。你正在面试候选人 {interview.name or '先生/女士'}，岗位是 {interview.position or '基础岗位'}。

岗位背景信息 (JD)：
{jd_info}

本次面试流程：
1. **自我介绍** (intro)：请候选人进行简短的自我介绍。
2. **主问题问答** (qa)：根据题目列表进行提问，并根据节奏进行追问。
3. **自然结束** (closing)：主问题结束后礼貌地结束面试。

本次面试规则与参数：
1. **主问题数量**：本次面试共包含 {main_question_count} 个主问题。
2. **追问限额**：每个主问题之后，最多允许进行 {followup_limit} 次简短追问。
3. **预期时长**：整场面试大约持续 {expected_duration} 分钟。
4. **节奏控制**：
   - 如果候选人回答简短且有必要，可以进行追问。
   - 如果面试时间紧迫（你会收到系统提示），请减少或停止追问，优先完成所有主问题。
5. **每次只问一个问题**：确保候选人回答完当前问题后，再进入下一个。
6. **回答完整性检查**：
   - 请根据提供的"参考方向/要点"和"岗位背景信息"来判断候选人的回答是否完整。
   - 如果回答明显不完整或遗漏关键点，且时间允许，请使用简短的话语提示引导候选人补充。
7. **被打断处理**：如果候选人在你确认回答完整前提到新话题，先简短回应，然后提醒"我们先把刚才那个问题说完"。
8. **长时间未回答**：若你收到系统提示"候选人尚未回答"，请简短重复当前问题或礼貌提醒候选人作答（例如："您可以先简单说说想法，不必紧张。"），不要换题。
9. **跑题引导（高优先级）**：
   - 如果候选人询问与本次能力评估无关的 HR 或公司类话题（如：薪资、福利、职级、假期、制度、团队文化、具体业务细节、公司发展等），请统一回复："本次面试仅作为能力评估，关于公司文化、薪资、制度等其他话题后续会由 HR 或人工面试官为您处理。我们现在继续回到面试中。"
   - 回复后，请立即将话题拉回到当前的面试题目或流程中。
10. **面试结束提示**：在面试进入 closing 阶段并完成结语时，请务必包含以下提示："本次面试到这里就结束了。您可以手动点击'结束面试'按钮，系统也会在稍后自动为您提交。感谢您的参与！"
11. **语气与语言**：语气要专业、礼貌且富有同理心。整个过程请使用中文。

题目列表与参考方向：
{questions_str}
""",
                    "voice": "alloy",
                    "modalities": ["text", "audio"],
                    "input_audio_format": "pcm16",
                    "output_audio_format": "pcm16",
                    "input_audio_transcription": {
                        "model": "whisper-1"
                    },
                    "turn_detection": {
                        "type": "server_vad",
                        "threshold": 0.5,
                        "prefix_padding_ms": 300,
                        "silence_duration_ms": 1200,
                        "create_response": False  # Manual turn control
                    },
                }
            }
            await openai_ws.send(json.dumps(init_event))
            await asyncio.sleep(0.5)  # Give OpenAI some time to process session update

            # Track current state
            audio_buffer = []
            is_recording_segment = False

            # Runtime pacing states
            interview_start_ts = time.time()
            time_budget_sec = expected_duration * 60
            ordered_questions = sorted(
                interview.question_set or [],
                key=lambda q: q.get("order_index", 0),
            )
            main_count_target = min(main_question_count, len(ordered_questions))

            # Business state (will be updated only on turn completion)
            main_questions_completed = 0
            current_main_question_order = 0
            followups_used_for_current = 0
            overtime_mode = False
            overtime_closing_sent = False
            candidate_speaking = False
            natural_end_sent = False
            current_stage = InterviewStage.INTRO
            expected_candidate_reply_for = "intro"

            # Commit tracking
            commit_pending = False
            last_committed_item_id = None
            current_input_item_id = None
            has_uncommitted_audio = False

            # Pending plan (created after speech_stopped, applied on turn completion)
            pending_plan: Optional[TurnPlan] = None
            recent_dialogue_turns: list[dict[str, str]] = []

            def log_turn_state(event: str, extra: dict = None, **kwargs):
                """Enhanced logging with turn context. kwargs are passed through to log_interview_event (e.g. duration_ms)."""
                active_turn = orchestrator.get_active_turn()
                log_interview_event(
                    event_name=event,
                    interview_id=interview.id,
                    interview_token=token,
                    source="turn_orchestrator",
                    stage=current_stage.value,
                    turn_id=active_turn.turn_id if active_turn else None,
                    details=extra,
                    question_order=current_main_question_order,
                    main_completed_count=main_questions_completed,
                    followups_used=followups_used_for_current,
                    expected_reply=expected_candidate_reply_for,
                    overtime_mode=overtime_mode,
                    turn_status=active_turn.status.value if active_turn else None,
                    **kwargs
                )

            log_turn_state("INTERVIEW_SESSION_START", {
                "candidate": interview.name,
                "position": interview.position,
                "main_question_count": main_question_count,
                "main_count_target": main_count_target,
                "followup_limit": followup_limit,
                "expected_duration": expected_duration
            })
            logger.info("Interview started: id=%s, token=%s", interview.id, token)

            def get_main_question(order: int):
                if order <= 0 or order > len(ordered_questions):
                    return None
                return ordered_questions[order - 1]

            def build_main_question_instruction(order: int) -> str:
                question = get_main_question(order)
                if not question:
                    return build_closing_instruction()
                
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
                    f"现在进入第 {order}/{main_count_target} 个主问题。"
                    f"你必须先明确提出这道主问题（不要继续停留在自我介绍追问）："
                    f"{question_text}。{reference_hint}"
                    f"提问时请先说明'主问题第{order}题'，并围绕该题作答。一次只问一个问题。"
                )

            def build_followup_instruction(order: int) -> str:
                question = get_main_question(order)
                question_text = (question or {}).get("question_text", "").strip()
                
                if settings.REALTIME_STRICT_PROMPT_ENABLED:
                    return (
                        f"[INTERVIEW_STAGE] qa_followup\n"
                        f"[QUESTION_ID] {order}\n"
                        f"[CONTEXT] 围绕主问题：{question_text}\n"
                        f"[ALLOWED_ACTION] followup_only\n"
                        f"[INSTRUCTION] 请针对候选人刚才的回答做一个极简追问。追问必须聚焦于该主问题的关键遗漏点。禁止切换话题，禁止进入下一题。"
                    )
                
                return (
                    f"请围绕刚才这个主问题做一次简短追问（第 {order} 题：{question_text}）。"
                    "追问要短、聚焦关键遗漏点，不要切换到新主问题。"
                )

            def build_closing_instruction() -> str:
                if settings.REALTIME_STRICT_PROMPT_ENABLED:
                    return (
                        f"[INTERVIEW_STAGE] closing\n"
                        f"[INSTRUCTION] 所有主问题已完成。请立即礼貌结束面试。禁止提出任何新问题。\n"
                        f"[REQUIRED_TEXT] 「本次面试到这里就结束了。您可以手动点击'结束面试'按钮，系统也会在稍后自动为您提交。感谢您的参与！」"
                    )
                
                return (
                    "所有主问题已完成。请立即进入 closing 阶段，礼貌结束面试，"
                    "并务必包含以下提示："
                    "「本次面试到这里就结束了。您可以手动点击'结束面试'按钮，"
                    "系统也会在稍后自动为您提交。感谢您的参与！」"
                    "结束后不要再提出新问题。"
                )

            def build_hr_redirect_instruction() -> str:
                if settings.REALTIME_STRICT_PROMPT_ENABLED:
                    return (
                        "[INTERVIEW_STAGE] qa_redirect\n"
                        "[INSTRUCTION] 候选人提出了流程/岗位/HR相关问题。请先用一句话简短回答："
                        "本次面试仅作为能力评估，关于公司文化、薪资、制度等后续会由 HR 或人工面试官处理。"
                        "随后立刻回到当前面试问题，要求候选人继续回答。"
                    )
                return (
                    "候选人刚才在提问。请先简短回应：本次面试仅作为能力评估，"
                    "公司文化、薪资、制度等问题后续由 HR 或人工面试官处理。"
                    "然后立即把话题拉回当前问题，请候选人继续回答。"
                )

            def legacy_rule_plan_next_turn_after_candidate_input() -> Optional[TurnPlan]:
                """Plan the next turn based on current state (not yet committed)"""
                nonlocal overtime_mode, overtime_closing_sent

                elapsed = time.time() - interview_start_ts
                elapsed_ratio = elapsed / time_budget_sec if time_budget_sec > 0 else 0

                # Check for overtime
                if elapsed >= time_budget_sec and not overtime_mode:
                    log_turn_state("INTERVIEW_OVERTIME_ENTERED", {"elapsed_seconds": round(elapsed, 1)})
                    overtime_mode = True

                # Check for hard timeout
                hard_timeout_buffer = max(time_budget_sec * 0.2, 300)
                if elapsed >= (time_budget_sec + hard_timeout_buffer):
                    return TurnPlan(
                        turn_kind=TurnKind.HARD_TIMEOUT_PROMPT,
                        stage_after_completion=InterviewStage.CLOSING,
                        question_order_after_completion=current_main_question_order,
                        expected_reply_after_completion=None,
                        control_instruction="面试时间已严重超时，请立即告知候选人面试必须结束，并直接进行结语。然后停止发言。",
                        advance_main_completed=False,
                        next_followups_used=0
                    )

                # Handle overtime
                if overtime_mode:
                    if not overtime_closing_sent:
                        overtime_closing_sent = True
                        return TurnPlan(
                            turn_kind=TurnKind.CLOSING_PROMPT,
                            stage_after_completion=InterviewStage.CLOSING,
                            question_order_after_completion=current_main_question_order,
                            expected_reply_after_completion=None,
                            control_instruction=(
                                "面试时间已到。请不要再问新的主问题或追问，"
                                "礼貌自然地结束面试。如果候选人刚才在提问，"
                                "请简短回答后结束。进入 closing stage。"
                            ),
                            advance_main_completed=False,
                            next_followups_used=0
                        )
                    else:
                        return TurnPlan(
                            turn_kind=TurnKind.CLOSING_PROMPT,
                            stage_after_completion=InterviewStage.CLOSING,
                            question_order_after_completion=current_main_question_order,
                            expected_reply_after_completion=None,
                            control_instruction=build_closing_instruction(),
                            advance_main_completed=False,
                            next_followups_used=0
                        )

                # Normal flow based on current stage
                if current_stage == InterviewStage.INTRO:
                    if main_count_target <= 0:
                        return TurnPlan(
                            turn_kind=TurnKind.CLOSING_PROMPT,
                            stage_after_completion=InterviewStage.CLOSING,
                            question_order_after_completion=0,
                            expected_reply_after_completion=None,
                            control_instruction=build_closing_instruction(),
                            advance_main_completed=False,
                            next_followups_used=0
                        )
                    else:
                        # Move to first main question
                        return TurnPlan(
                            turn_kind=TurnKind.MAIN_PROMPT,
                            stage_after_completion=InterviewStage.QA,
                            question_order_after_completion=1,
                            expected_reply_after_completion="main",
                            control_instruction=build_main_question_instruction(1),
                            advance_main_completed=False,
                            next_followups_used=0
                        )

                elif current_stage == InterviewStage.QA:
                    # Determine what kind of answer we just received
                    # Only advance main question counter if candidate just answered a main question
                    advance_main = (expected_candidate_reply_for == "main")
                    next_completed = main_questions_completed + (1 if advance_main else 0)

                    # 1. Check if we should do a FOLLOWUP for the CURRENT question
                    # This must happen BEFORE checking if we should close, so the last question can have followups.
                    can_followup = (
                        advance_main and
                        followups_used_for_current < followup_limit and
                        current_main_question_order > 0 and
                        expected_duration > 0 and
                        elapsed_ratio <= 0.95
                    )

                    if can_followup:
                        # Do a followup for the current main question
                        return TurnPlan(
                            turn_kind=TurnKind.FOLLOWUP_PROMPT,
                            stage_after_completion=InterviewStage.QA,
                            question_order_after_completion=current_main_question_order,
                            expected_reply_after_completion="followup",
                            control_instruction=build_followup_instruction(current_main_question_order),
                            advance_main_completed=True,  # We did complete the main question
                            next_followups_used=followups_used_for_current + 1
                        )

                    # 2. Check if all main questions are completed
                    if next_completed >= main_count_target:
                        # Before closing, check if the last answer was substantive (Answer Gate)
                        if advance_main:
                            user_transcript = orchestrator.get_user_transcript(current_input_item_id) if current_input_item_id else ""
                            is_substantive = True
                            gate_reason = None
                            
                            if not user_transcript:
                                is_substantive = False
                                gate_reason = "empty_transcript"
                            else:
                                clean_text = re.sub(r"[，。！？；、,.!?;:\s（）()]+", "", user_transcript)
                                if len(clean_text) < settings.REALTIME_MIN_MAIN_ANSWER_CHARS:
                                    is_substantive = False
                                    gate_reason = f"too_short({len(clean_text)})"
                                
                                confirm_words = [w.strip() for w in settings.REALTIME_MAIN_ANSWER_CONFIRM_WORDS.split(",") if w.strip()]
                                if clean_text in confirm_words:
                                    is_substantive = False
                                    gate_reason = "confirm_word_only"

                            if not is_substantive:
                                log_turn_state("CLOSING_BLOCKED_BY_ANSWER_GATE", {
                                    "reason": gate_reason,
                                    "transcript": user_transcript,
                                    "target_q": current_main_question_order
                                })
                                # Re-ask the current main question instead of closing
                                question = get_main_question(current_main_question_order) or {}
                                return TurnPlan(
                                    turn_kind=TurnKind.REASK_PROMPT,
                                    stage_after_completion=InterviewStage.QA,
                                    question_order_after_completion=current_main_question_order,
                                    expected_reply_after_completion="main",
                                    control_instruction=(
                                        f"[INTERVIEW_STAGE] qa_main_retry\n"
                                        f"[INSTRUCTION] 刚才的回答比较简短。请围绕第{current_main_question_order}题补充更多细节：\n"
                                        f"{question.get('question_text', '').strip()}\n"
                                        f"你可以从具体案例、实施过程或遇到的挑战等方面进行补充。"
                                    ),
                                    advance_main_completed=False, # Stay on current question
                                    next_followups_used=followups_used_for_current
                                )

                        # All main questions completed and passed gate
                        return TurnPlan(
                            turn_kind=TurnKind.CLOSING_PROMPT,
                            stage_after_completion=InterviewStage.CLOSING,
                            question_order_after_completion=current_main_question_order,
                            expected_reply_after_completion=None,
                            control_instruction=build_closing_instruction(),
                            advance_main_completed=advance_main,
                            next_followups_used=0
                        )

                    # 3. Move to the next main question
                    if expected_candidate_reply_for == "followup" or advance_main:
                        # Move to next main question
                        next_order = next_completed + 1
                        return TurnPlan(
                            turn_kind=TurnKind.MAIN_PROMPT,
                            stage_after_completion=InterviewStage.QA,
                            question_order_after_completion=next_order,
                            expected_reply_after_completion="main",
                            control_instruction=build_main_question_instruction(next_order),
                            advance_main_completed=advance_main,
                            next_followups_used=0  # Reset followups for new question
                        )

                elif current_stage == InterviewStage.CLOSING:
                    # Already in closing, keep closing
                    return TurnPlan(
                        turn_kind=TurnKind.CLOSING_PROMPT,
                        stage_after_completion=InterviewStage.CLOSING,
                        question_order_after_completion=current_main_question_order,
                        expected_reply_after_completion=None,
                        control_instruction=build_closing_instruction(),
                        advance_main_completed=False,
                        next_followups_used=0
                    )

                return None

            def _add_dialogue_turn(role: str, text: str) -> None:
                snippet = _clamp_text(text, 500)
                if not snippet:
                    return
                recent_dialogue_turns.append({"role": role, "text": snippet})
                max_entries = max(settings.REALTIME_DECISION_HISTORY_TURNS * 2, 4)
                if len(recent_dialogue_turns) > max_entries:
                    del recent_dialogue_turns[:-max_entries]

            async def wait_for_user_transcript(item_id: Optional[str]) -> str:
                """
                Wait briefly for the latest user transcript so decision layer can
                consume fresh candidate content instead of stale history.
                """
                if not item_id:
                    return ""

                existing = orchestrator.get_user_transcript(item_id) or ""
                if existing:
                    return existing

                started = time.time()
                timeout_sec = max(TRANSCRIPT_WAIT_MAX_MS, 0) / 1000.0
                poll_sec = max(TRANSCRIPT_WAIT_POLL_MS, 10) / 1000.0
                deadline = started + timeout_sec

                while time.time() < deadline:
                    await asyncio.sleep(poll_sec)
                    transcript = orchestrator.get_user_transcript(item_id) or ""
                    if transcript:
                        waited_ms = int((time.time() - started) * 1000)
                        log_turn_state("USER_TRANSCRIPT_READY_BEFORE_DECISION", {
                            "item_id": item_id,
                            "waited_ms": waited_ms,
                            "chars": len(transcript),
                        })
                        return transcript

                waited_ms = int((time.time() - started) * 1000)
                log_turn_state("USER_TRANSCRIPT_WAIT_TIMEOUT", {
                    "item_id": item_id,
                    "waited_ms": waited_ms,
                })
                return ""

            def get_allowed_decision_actions() -> set[str]:
                actions = {"answer_candidate_question", "clarify"}
                can_finish_now = (
                    main_count_target <= 0 or
                    main_questions_completed >= main_count_target
                )
                if current_stage == InterviewStage.INTRO:
                    actions.add("next_question")
                elif current_stage == InterviewStage.QA:
                    actions.add("next_question")
                    if current_main_question_order > 0:
                        actions.add("followup")
                elif current_stage == InterviewStage.CLOSING and can_finish_now:
                    actions.add("finish_interview")

                if can_finish_now:
                    actions.add("finish_interview")
                return actions

            def build_decision_context(latest_candidate_utterance: str) -> dict[str, Any]:
                history_turns = max(settings.REALTIME_DECISION_HISTORY_TURNS, 1)
                max_chars = max(settings.REALTIME_DECISION_MAX_CHARS, 200)
                current_question = get_main_question(current_main_question_order) if current_main_question_order > 0 else None
                recent_pairs = recent_dialogue_turns[-(history_turns * 2):]
                recent_summary = [
                    f"{item.get('role', 'Unknown')}: {item.get('text', '')}"
                    for item in recent_pairs
                    if item.get("text")
                ]
                remaining_main_questions = max(main_count_target - main_questions_completed, 0)
                return {
                    "stage": current_stage.value,
                    "question_order": current_main_question_order,
                    "question_text": (current_question or {}).get("question_text", ""),
                    "expected_reply_for": expected_candidate_reply_for,
                    "latest_candidate_utterance": _clamp_text(latest_candidate_utterance, max_chars),
                    "recent_dialogue_summary": "\n".join(recent_summary),
                    "main_questions_completed": main_questions_completed,
                    "main_count_target": main_count_target,
                    "remaining_main_questions": remaining_main_questions,
                    "can_finish_now": remaining_main_questions <= 0,
                    "followups_used_for_current": followups_used_for_current,
                    "followup_limit": followup_limit,
                    "allowed_actions": sorted(get_allowed_decision_actions()),
                }

            async def call_decision_llm(context: dict[str, Any]) -> tuple[Optional[dict], Optional[str], int]:
                if not decision_client:
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
                        decision_client.chat.completions.create(
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
                    decision, parse_error = _parse_and_validate_decision(
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

            def map_decision_to_turn_plan(decision: dict[str, Any]) -> Optional[TurnPlan]:
                action = decision.get("action")
                decision_reason = str(decision.get("reason") or "").strip()
                reason_suffix = f"（决策原因：{decision_reason}）" if decision_reason else ""

                def build_next_question_plan() -> TurnPlan:
                    if current_stage == InterviewStage.INTRO:
                        if main_count_target <= 0:
                            return TurnPlan(
                                turn_kind=TurnKind.CLOSING_PROMPT,
                                stage_after_completion=InterviewStage.CLOSING,
                                question_order_after_completion=0,
                                expected_reply_after_completion=None,
                                control_instruction=build_closing_instruction(),
                                advance_main_completed=False,
                                next_followups_used=0,
                            )
                        return TurnPlan(
                            turn_kind=TurnKind.MAIN_PROMPT,
                            stage_after_completion=InterviewStage.QA,
                            question_order_after_completion=1,
                            expected_reply_after_completion="main",
                            control_instruction=f"{build_main_question_instruction(1)}{reason_suffix}",
                            advance_main_completed=False,
                            next_followups_used=0,
                        )

                    advance_main = (expected_candidate_reply_for == "main")
                    next_completed = main_questions_completed + (1 if advance_main else 0)
                    if next_completed >= main_count_target:
                        return TurnPlan(
                            turn_kind=TurnKind.CLOSING_PROMPT,
                            stage_after_completion=InterviewStage.CLOSING,
                            question_order_after_completion=current_main_question_order,
                            expected_reply_after_completion=None,
                            control_instruction=build_closing_instruction(),
                            advance_main_completed=advance_main,
                            next_followups_used=0,
                        )

                    next_order = next_completed + 1
                    return TurnPlan(
                        turn_kind=TurnKind.MAIN_PROMPT,
                        stage_after_completion=InterviewStage.QA,
                        question_order_after_completion=next_order,
                        expected_reply_after_completion="main",
                        control_instruction=f"{build_main_question_instruction(next_order)}{reason_suffix}",
                        advance_main_completed=advance_main,
                        next_followups_used=0,
                    )

                if action == "finish_interview":
                    if main_count_target > 0 and main_questions_completed < main_count_target:
                        next_order = min(main_questions_completed + 1, main_count_target)
                        fallback_plan = TurnPlan(
                            turn_kind=TurnKind.MAIN_PROMPT,
                            stage_after_completion=InterviewStage.QA,
                            question_order_after_completion=next_order,
                            expected_reply_after_completion="main",
                            control_instruction=f"{build_main_question_instruction(next_order)}{reason_suffix}",
                            advance_main_completed=False,
                            next_followups_used=0,
                        )
                        log_turn_state("decision_layer.finish_blocked", {
                            "action": action,
                            "main_questions_completed": main_questions_completed,
                            "main_count_target": main_count_target,
                            "expected_reply_for": expected_candidate_reply_for,
                            "fallback_action": "next_question",
                        })
                        return fallback_plan
                    return TurnPlan(
                        turn_kind=TurnKind.CLOSING_PROMPT,
                        stage_after_completion=InterviewStage.CLOSING,
                        question_order_after_completion=current_main_question_order,
                        expected_reply_after_completion=None,
                        control_instruction=build_closing_instruction(),
                        advance_main_completed=False,
                        next_followups_used=0,
                    )

                if action == "answer_candidate_question":
                    return TurnPlan(
                        turn_kind=TurnKind.HR_REDIRECT_PROMPT,
                        stage_after_completion=current_stage,
                        question_order_after_completion=current_main_question_order,
                        expected_reply_after_completion=expected_candidate_reply_for,
                        control_instruction=f"{build_hr_redirect_instruction()}{reason_suffix}",
                        advance_main_completed=False,
                        next_followups_used=followups_used_for_current,
                    )

                if action == "clarify":
                    question = get_main_question(current_main_question_order) or {}
                    if current_stage == InterviewStage.QA and current_main_question_order > 0:
                        clarify_instruction = (
                            f"[INTERVIEW_STAGE] qa_clarify\n"
                            f"[INSTRUCTION] 候选人表示未理解问题。请重新解释并重述第{current_main_question_order}题：\n"
                            f"{question.get('question_text', '').strip()}。"
                            f"解释要简短清晰，然后请候选人继续回答。{reason_suffix}"
                        )
                        expected_reply_after = "main"
                    else:
                        clarify_instruction = (
                            "候选人表示没听清。请用更简洁的话重新说明你刚才的问题，"
                            "并等待候选人继续回答。"
                        )
                        expected_reply_after = expected_candidate_reply_for

                    return TurnPlan(
                        turn_kind=TurnKind.REASK_PROMPT,
                        stage_after_completion=current_stage,
                        question_order_after_completion=current_main_question_order,
                        expected_reply_after_completion=expected_reply_after,
                        control_instruction=clarify_instruction,
                        advance_main_completed=False,
                        next_followups_used=followups_used_for_current,
                    )

                if action == "followup":
                    if current_stage != InterviewStage.QA or current_main_question_order <= 0:
                        return None
                    return TurnPlan(
                        turn_kind=TurnKind.FOLLOWUP_PROMPT,
                        stage_after_completion=InterviewStage.QA,
                        question_order_after_completion=current_main_question_order,
                        expected_reply_after_completion="followup",
                        control_instruction=f"{build_followup_instruction(current_main_question_order)}{reason_suffix}",
                        advance_main_completed=(expected_candidate_reply_for == "main"),
                        next_followups_used=min(followups_used_for_current + 1, followup_limit),
                    )

                if action == "next_question":
                    return build_next_question_plan()

                return None

            async def decide_next_turn_after_candidate_input() -> Optional[TurnPlan]:
                latest_utterance = orchestrator.get_user_transcript(current_input_item_id) if current_input_item_id else ""
                latest_utterance = latest_utterance or ""
                if not latest_utterance:
                    for item in reversed(recent_dialogue_turns):
                        if item.get("role") == "Candidate" and item.get("text"):
                            latest_utterance = item["text"]
                            break
                fallback_plan = legacy_rule_plan_next_turn_after_candidate_input()

                if not settings.REALTIME_DECISION_LAYER_ENABLED:
                    return fallback_plan

                context = build_decision_context(latest_utterance)
                log_turn_state("decision_layer.requested", {
                    "input_chars": len(context.get("latest_candidate_utterance", "")),
                    "history_chars": len(context.get("recent_dialogue_summary", "")),
                    "allowed_actions": context.get("allowed_actions", []),
                })

                decision, error_reason, latency_ms = await call_decision_llm(context)
                if error_reason or not decision:
                    log_turn_state(
                        "decision_layer.fallback",
                        {"reason": error_reason or "unknown_error", "latency_ms": latency_ms},
                        duration_ms=latency_ms,
                    )
                    return fallback_plan

                plan = map_decision_to_turn_plan(decision)
                if not plan:
                    log_turn_state(
                        "decision_layer.fallback",
                        {"reason": "mapping_failed", "action": decision.get("action"), "decision_reason": decision.get("reason"), "latency_ms": latency_ms},
                        duration_ms=latency_ms,
                    )
                    return fallback_plan

                log_turn_state(
                    "decision_layer.succeeded",
                    {"action": decision.get("action"), "reason": decision.get("reason"), "latency_ms": latency_ms},
                    duration_ms=latency_ms,
                )
                log_turn_state("decision_layer.mapped_to_plan", {
                    "action": decision.get("action"),
                    "reason": decision.get("reason"),
                    "plan": plan.to_log_dict(),
                })
                return plan

            async def send_response_create_with_turn(plan: TurnPlan):
                """Send response.create and create a turn"""
                nonlocal pending_plan, current_main_question_order

                if orchestrator.has_pending_turn():
                    log_turn_state("AI_RESPONSE_CREATE_SKIPPED", {
                        "reason": "pending_turn",
                        "plan": plan.to_log_dict() if plan else None
                    })
                    return

                # Context Reset Logic
                if settings.REALTIME_CONTEXT_RESET_MODE == "per_main_question":
                    # If we are moving to a NEW main question OR entering closing, clear conversation history
                    is_new_main = (plan.turn_kind == TurnKind.MAIN_PROMPT and 
                                 plan.question_order_after_completion != current_main_question_order)
                    is_entering_closing = (plan.turn_kind == TurnKind.CLOSING_PROMPT and current_stage != InterviewStage.CLOSING)
                    
                    if is_new_main or is_entering_closing:
                        reason = "new_main" if is_new_main else "closing"
                        
                        log_details = {"reason": reason}
                        if is_new_main:
                            log_details["target_q"] = plan.question_order_after_completion
                            
                        log_turn_state("CONTEXT_RESET_START", log_details)
                        
                        # Use session.update to reset or just clear items if the API supports it.
                        # For Realtime API, the most reliable way to "clear" without reconnecting 
                        # is to send a session.update with the base instructions again, 
                        # but that doesn't clear history. 
                        # To truly clear history, we'd need to reconnect or use conversation.item.delete (if available).
                        # A common trick is to update instructions to be very strict about "forgetting" or 
                        # simply rely on the fact that we are driving the turn.
                        # HOWEVER, the best way is to actually reconnect or send a 'session.update' 
                        # that might trigger a fresh state if the model supports it.
                        # Since we want "hard reset", let's try to send a session.update with a 'reset' hint 
                        # or just accept that we'll implement it by making sure the model doesn't see old items.
                        # Actually, let's implement a "soft" reset by re-sending session.update first.
                        
                        reset_event = {
                            "type": "session.update",
                            "session": {
                                "instructions": init_event["session"]["instructions"] # Re-inject base instructions
                            }
                        }
                        await openai_ws.send(json.dumps(reset_event))
                        log_turn_state("CONTEXT_RESET_APPLIED")

                # Create turn
                turn = orchestrator.create_turn(
                    plan=plan,
                    current_stage=current_stage,
                    expected_reply_before=expected_candidate_reply_for,
                    question_order=current_main_question_order
                )

                # Store the plan for later application
                pending_plan = plan

                # Send response.create
                response_payload = {
                    "type": "response.create",
                    "response": {
                        "instructions": plan.control_instruction
                    }
                }
                await openai_ws.send(json.dumps(response_payload))

                log_turn_state("AI_NEXT_TURN", {
                    "turn_id": turn.turn_id,
                    "turn_kind": turn.turn_kind.value,
                    "instructions_preview": plan.control_instruction[:100]
                })

            async def commit_input_audio_once(reason: str, item_id: str = None):
                nonlocal commit_pending, last_committed_item_id, has_uncommitted_audio
                resolved_item_id = item_id or current_input_item_id

                active_turn = orchestrator.get_active_turn()
                log_turn_state("COMMIT_ATTEMPT", {
                    "reason": reason,
                    "item_id": resolved_item_id,
                    "turn_id": active_turn.turn_id if active_turn else None,
                    "has_uncommitted": has_uncommitted_audio
                })

                if not has_uncommitted_audio:
                    log_turn_state("COMMIT_SKIPPED_NO_AUDIO", {
                        "reason": reason,
                        "item_id": resolved_item_id
                    })
                    return False

                if commit_pending:
                    log_turn_state("COMMIT_SKIPPED_DUPLICATE", {
                        "reason": f"{reason}:pending",
                        "item_id": resolved_item_id,
                        "last_committed_item_id": last_committed_item_id
                    })
                    return False

                if resolved_item_id and resolved_item_id == last_committed_item_id:
                    log_turn_state("COMMIT_SKIPPED_DUPLICATE", {
                        "reason": f"{reason}:already_committed",
                        "item_id": resolved_item_id,
                        "last_committed_item_id": last_committed_item_id
                    })
                    return False

                await openai_ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
                commit_pending = True
                return True

            def is_main_question_aligned(order: int, assistant_transcript: str):
                """Check if the assistant's response aligns with the expected main question"""
                question = get_main_question(order)
                if not question:
                    return True, []
                question_text = (question.get("question_text") or "").strip()
                if not question_text:
                    return True, []
                answer_text = (assistant_transcript or "").strip()
                if not answer_text:
                    return False, []

                normalized_q = re.sub(r"\s+", "", question_text)
                normalized_a = re.sub(r"\s+", "", answer_text)
                if normalized_q[:12] and normalized_q[:12] in normalized_a:
                    return True, []

                chunks = [
                    c for c in re.split(r"[，。！？；、,.!?;:\s（）()]+", question_text)
                    if len(c) >= 4
                ]
                matched = [c for c in chunks[:6] if c in normalized_a]
                if len(chunks) >= 2:
                    return len(matched) >= 2, matched
                return len(matched) >= 1, matched

            def apply_business_transition(transition: Optional[BusinessTransition]):
                """Apply business state transition after turn completion"""
                nonlocal current_stage, current_main_question_order, expected_candidate_reply_for
                nonlocal main_questions_completed, followups_used_for_current, natural_end_sent

                if not transition:
                    return

                # Apply state changes
                current_stage = transition.new_stage
                current_main_question_order = transition.new_question_order
                expected_candidate_reply_for = transition.new_expected_reply

                if transition.advance_main_completed:
                    main_questions_completed += 1

                followups_used_for_current = transition.new_followups_used

                # Handle natural end
                if transition.is_natural_end and not natural_end_sent:
                    log_turn_state("INTERVIEW_NATURAL_END_SENT")
                    asyncio.create_task(websocket.send_text(json.dumps({"type": "interview.natural_end"})))
                    natural_end_sent = True

            # 2. Start the conversation with intro prompt
            first_plan = TurnPlan(
                turn_kind=TurnKind.INTRO_PROMPT,
                stage_after_completion=InterviewStage.INTRO,
                question_order_after_completion=0,
                expected_reply_after_completion="intro",
                control_instruction=(
                    f"[INTERVIEW_STAGE] intro\n"
                    f"[INSTRUCTION] 请开始面试，向候选人问好并请他进行简短的自我介绍。禁止直接开始提问主问题。"
                    if settings.REALTIME_STRICT_PROMPT_ENABLED else
                    "请开始面试，向候选人问好并请他进行简短的自我介绍。这是面试的第一步 (intro stage)。"
                ),
                advance_main_completed=False,
                next_followups_used=0
            )
            await send_response_create_with_turn(first_plan)

            # Relay tasks
            async def relay_client_to_openai():
                nonlocal candidate_speaking
                try:
                    async for message in websocket.iter_text():
                        data = json.loads(message)
                        if data.get("type") == "audio":
                            audio_data = data["audio"]
                            raw_audio = base64.b64decode(audio_data)
                            has_uncommitted_audio = True

                            # Only buffer if we are in a speech segment
                            if is_recording_segment:
                                audio_buffer.append(raw_audio)

                            # Always relay to OpenAI for VAD
                            audio_event = {
                                "type": "input_audio_buffer.append",
                                "audio": audio_data
                            }
                            await openai_ws.send(json.dumps(audio_event))

                        elif data.get("type") == "end_turn":
                            log_turn_state("CLIENT_END_TURN_REQUESTED")
                            await commit_input_audio_once("client_end_turn")
                            await wait_for_user_transcript(current_input_item_id)
                            plan = await decide_next_turn_after_candidate_input()
                            if plan:
                                await send_response_create_with_turn(plan)

                        elif data.get("type") == "no_response_timeout":
                            if current_stage != InterviewStage.CLOSING and not overtime_mode and not candidate_speaking:
                                log_turn_state("NO_RESPONSE_TIMEOUT_TRIGGERED")
                                reask_plan = TurnPlan(
                                    turn_kind=TurnKind.REASK_PROMPT,
                                    stage_after_completion=current_stage,
                                    question_order_after_completion=current_main_question_order,
                                    expected_reply_after_completion=expected_candidate_reply_for,
                                    control_instruction="候选人尚未回答。请简短重复当前问题或礼貌提醒候选人作答（例如：您可以先简单说说想法。），不要换题。",
                                    advance_main_completed=False,
                                    next_followups_used=followups_used_for_current
                                )
                                await send_response_create_with_turn(reask_plan)

                except Exception as e:
                    log_interview_event(
                        event_name="relay.client_to_openai.error",
                        interview_id=interview.id,
                        interview_token=token,
                        level=logging.ERROR,
                        source="api.realtime",
                        outcome="failed",
                        error_message=str(e),
                    )

            async def relay_openai_to_client():
                nonlocal is_recording_segment, candidate_speaking, pending_plan
                nonlocal current_input_item_id, commit_pending, last_committed_item_id

                try:
                    async for message in openai_ws:
                        event = json.loads(message)
                        event_type = event.get("type")

                        # Log non-delta events
                        if event_type not in ["response.audio.delta", "response.audio_transcript.delta", "response.text.delta"]:
                            # Skip common events to avoid cluttering Server Log
                            if event_type not in ["input_audio_buffer.append", "input_audio_buffer.speech_started", "input_audio_buffer.speech_stopped", "response.audio.delta", "response.text.delta", "response.audio_transcript.delta"]:
                                pass # Already handled by log_interview_event or too verbose

                        # 1. Handle Audio/Text Deltas for UI
                        if event_type in ["response.audio.delta", "response.text.delta", "response.audio_transcript.delta"]:
                            # Handle response.audio.delta properly
                            if event_type == "response.audio.delta":
                                delta_audio = event.get("delta", "")
                                if delta_audio:
                                    # Record AI audio output usage (assuming 24kHz PCM16)
                                    try:
                                        pcm_bytes = base64.b64decode(delta_audio)
                                        # 24kHz * 2 bytes per sample = 48000 bytes per second
                                        usage_tracker.add_audio_usage(
                                            model_name="gpt-realtime-mini",
                                            output_seconds=len(pcm_bytes) / 48000.0
                                        )
                                    except Exception as e:
                                        log_interview_event(
                                            event_name="usage.audio_delta_decode_failed",
                                            interview_id=interview.id,
                                            interview_token=token,
                                            level=logging.ERROR,
                                            source="api.realtime",
                                            outcome="failed",
                                            error_message=str(e),
                                        )

                                if "delta" in event:
                                    modified_event = event.copy()
                                    modified_event["audio"] = event["delta"]
                                    await websocket.send_text(json.dumps(modified_event))
                                else:
                                    await websocket.send_text(json.dumps(event))
                            else:
                                await websocket.send_text(json.dumps(event))

                            # Accumulate transcript
                            if event_type == "response.audio_transcript.delta":
                                response_id = event.get("response_id")
                                if response_id:
                                    orchestrator.append_transcript_delta(response_id, event.get("delta", ""))

                        # 2. Handle response.created - bind to turn
                        elif event_type == "response.created":
                            response = event.get("response", {})
                            response_id = response.get("id")
                            if response_id:
                                turn = orchestrator.bind_response(response_id)
                                if turn:
                                    log_turn_state("AI_RESPONSE_CREATED", {
                                        "response_id": response_id,
                                        "turn_id": turn.turn_id,
                                        "turn_kind": turn.turn_kind.value
                                    })
                            await websocket.send_text(json.dumps(event))

                        # 3. Handle response.done with outcome classification
                        elif event_type == "conversation.item.input_audio_transcription.completed":
                            item_id = event.get("item_id")
                            transcript = event.get("transcript", "")
                            if transcript:
                                orchestrator.set_user_transcript(item_id, transcript)
                                # Write to Dialogue Log immediately
                                log_dialogue_line(
                                    interview_token=token,
                                    role="Candidate",
                                    text=transcript
                                )
                                _add_dialogue_turn("Candidate", transcript)

                        elif event_type == "response.done":
                            response = event.get("response", {})
                            response_id = response.get("id")
                            status = response.get("status")
                            status_details = response.get("status_details", {})
                            usage = response.get("usage")
                            
                            if usage:
                                model_name = "gpt-realtime-mini" # Default or from response if available
                                usage_tracker.add_text_usage(
                                    model_name=model_name,
                                    input_tokens=usage.get("input_tokens", 0),
                                    output_tokens=usage.get("output_tokens", 0)
                                )
                                # Realtime API also provides audio tokens in usage, but user wants seconds for audio if possible.
                                # However, for consistency with text, we could also store audio_tokens if they exist.
                                # For now, let's stick to the plan of using audio seconds from VAD.

                            log_interview_event(
                                event_name="openai.response.done",
                                interview_id=interview.id,
                                interview_token=token,
                                source="api.realtime",
                                openai_response_id=response_id,
                                outcome=status,
                                details={"usage": usage}
                            )

                            if status == "completed":
                                # Turn completed successfully
                                turn = orchestrator.complete_turn(response_id, usage)
                                if turn:
                                    # Check for main question drift
                                    if (turn.turn_kind == TurnKind.MAIN_PROMPT and
                                        turn.status == TurnStatus.COMPLETED):
                                        # Use turn's target question order for drift check
                                        check_q_order = turn.target_question_order or current_main_question_order
                                        
                                        aligned, matched_chunks = is_main_question_aligned(
                                            check_q_order,
                                            turn.transcript
                                        )
                                        if not aligned:
                                            question = get_main_question(check_q_order) or {}
                                            log_turn_state("MAIN_QUESTION_DRIFT_DETECTED", {
                                                "expected_question_order": check_q_order,
                                                "state_q_order": current_main_question_order,
                                                "expected_question_text": (question.get("question_text") or "")[:120],
                                                "actual_transcript_snippet": (turn.transcript or "")[:120],
                                                "matched_chunks": matched_chunks
                                            })
                                            
                                            # DRIFT_GUARD: Force REASK instead of applying transition
                                            if settings.REALTIME_STRICT_PROMPT_ENABLED:
                                                log_turn_state("DRIFT_BLOCKED", {"reason": "alignment_failed"})
                                                reask_plan = TurnPlan(
                                                    turn_kind=TurnKind.REASK_PROMPT,
                                                    stage_after_completion=current_stage,
                                                    question_order_after_completion=check_q_order,
                                                    expected_reply_after_completion=turn.target_expected_reply or expected_candidate_reply_for,
                                                    control_instruction=(
                                                        f"[INTERVIEW_STAGE] drift_correction\n"
                                                        f"[INSTRUCTION] 刚才的回答跑题了。请立即且仅能重述主问题第{check_q_order}题：\n"
                                                        f"{question.get('question_text', '').strip()}"
                                                    ),
                                                    advance_main_completed=False,
                                                    next_followups_used=followups_used_for_current
                                                )
                                                log_turn_state("DRIFT_REASK_CREATED", {
                                                    "source_turn_id": turn.turn_id,
                                                    "target_q": check_q_order
                                                })
                                                await send_response_create_with_turn(reask_plan)
                                                pending_plan = None
                                                continue

                                    # Apply business transition
                                    if pending_plan and orchestrator.should_advance_business_state(turn):
                                        transition = orchestrator.create_business_transition(pending_plan, turn)
                                        apply_business_transition(transition)
                                        pending_plan = None

                                    log_turn_state("AI_RESPONSE_DONE", {
                                        "turn_id": turn.turn_id,
                                        "transcript_len": len(turn.transcript)
                                    })
                                    
                                    # Write to Dialogue Log
                                    if turn.transcript:
                                        log_dialogue_line(
                                            interview_token=token,
                                            role="AI",
                                            text=turn.transcript
                                        )
                                        _add_dialogue_turn("AI", turn.transcript)

                            elif status == "cancelled":
                                # Turn was cancelled (e.g., turn_detected)
                                reason = status_details.get("reason", "unknown")
                                turn = orchestrator.cancel_turn(response_id, reason)
                                if turn:
                                    log_turn_state("AI_RESPONSE_CANCELLED", {
                                        "turn_id": turn.turn_id,
                                        "reason": reason
                                    })
                                # Don't apply transition for cancelled turns
                                pending_plan = None

                            elif status == "failed":
                                # Turn failed
                                error = status_details.get("error", {})
                                turn = orchestrator.fail_turn(
                                    response_id,
                                    error.get("code", "unknown"),
                                    error.get("message", "")
                                )
                                if turn:
                                    log_turn_state("AI_RESPONSE_FAILED", {
                                        "turn_id": turn.turn_id,
                                        "error_code": turn.error_code
                                    })
                                pending_plan = None

                        # 4. Handle Errors
                        elif event_type == "error":
                            err = event.get("error", {}) or {}
                            log_interview_event(
                                event_name="openai.error",
                                interview_id=interview.id,
                                interview_token=token,
                                level=logging.ERROR,
                                source="api.realtime",
                                outcome="failed",
                                error_code=err.get("code"),
                                error_message=err.get("message"),
                                details=event
                            )

                            if err.get("code") == "input_audio_buffer_commit_empty":
                                # This is a commit error, not a turn error
                                commit_pending = False
                                has_uncommitted_audio = False
                                log_turn_state("COMMIT_EMPTY_ERROR", {
                                    "error_code": err.get("code"),
                                    "error_message": err.get("message"),
                                    "item_id": current_input_item_id,
                                    "last_committed_item_id": last_committed_item_id
                                })
                            else:
                                # Other errors might affect the active turn
                                active_turn = orchestrator.get_active_turn()
                                if active_turn and active_turn.response_id:
                                    orchestrator.fail_turn(
                                        active_turn.response_id,
                                        err.get("code", "unknown"),
                                        err.get("message", "")
                                    )

                        # 5. Handle VAD Events
                        elif event_type == "input_audio_buffer.speech_started":
                            audio_start_ms = event.get("audio_start_ms", 0)
                            log_interview_event(
                                event_name="vad.speech_started",
                                interview_id=interview.id,
                                interview_token=token,
                                source="api.realtime",
                                stage=current_stage.value,
                                details={"audio_start_ms": audio_start_ms}
                            )
                            is_recording_segment = True
                            candidate_speaking = True
                            current_input_item_id = event.get("item_id")
                            audio_buffer.clear()

                        elif event_type == "input_audio_buffer.speech_stopped":
                            audio_end_ms = event.get("audio_end_ms", 0)
                            log_interview_event(
                                event_name="vad.speech_stopped",
                                interview_id=interview.id,
                                interview_token=token,
                                source="api.realtime",
                                stage=current_stage.value,
                                details={"audio_end_ms": audio_end_ms}
                            )
                            is_recording_segment = False
                            candidate_speaking = False
                            current_input_item_id = event.get("item_id") or current_input_item_id

                            # Filter out very short audio segments (less than 500ms)
                            # Check by audio buffer size as a proxy
                            MIN_AUDIO_BUFFER_SIZE = 5  # Minimum number of chunks
                            if len(audio_buffer) < MIN_AUDIO_BUFFER_SIZE:
                                log_turn_state("VAD_SPEECH_STOPPED_IGNORED", {
                                    "reason": "too_short",
                                    "buffer_size": len(audio_buffer)
                                })
                                audio_buffer.clear()
                                continue

                            # Skip if we have a pending turn
                            if orchestrator.has_pending_turn():
                                log_turn_state("VAD_SPEECH_STOPPED_IGNORED", {"reason": "turn_pending"})
                                audio_buffer.clear()
                                continue

                            await commit_input_audio_once("vad_speech_stopped", current_input_item_id)

                            # Save audio and record answer asynchronously
                            answer_question_index = 0
                            if expected_candidate_reply_for in ("main", "followup") and current_main_question_order > 0:
                                answer_question_index = current_main_question_order

                            if audio_buffer:
                                pcm_data = b"".join(audio_buffer)
                                
                                # Offload blocking I/O to a thread
                                try:
                                    user_transcript = orchestrator.get_user_transcript(current_input_item_id) if current_input_item_id else None
                                    file_path = await asyncio.to_thread(
                                        _persist_audio_and_answer_sync,
                                        pcm_data,
                                        interview.id,
                                        token,
                                        answer_question_index,
                                        user_transcript
                                    )

                                    log_interview_event(
                                        event_name="vad.segment_saved",
                                        interview_id=interview.id,
                                        interview_token=token,
                                        source="api.realtime",
                                        stage=current_stage.value,
                                        details={
                                            "file_path": file_path,
                                            "question_index": answer_question_index,
                                            "duration_ms": len(pcm_data) / 48 # 24kHz * 2 bytes = 48 bytes per ms
                                        }
                                    )
                                except Exception as e:
                                    log_interview_event(
                                        event_name="answer.persist_async_failed",
                                        interview_id=interview.id,
                                        interview_token=token,
                                        level=logging.ERROR,
                                        source="api.realtime",
                                        outcome="failed",
                                        error_message=str(e),
                                        details={"question_index": answer_question_index},
                                    )
                                    # We continue with the interview even if saving failed to avoid hanging the session

                                # Record audio input usage
                                usage_tracker.add_audio_usage(
                                    model_name="gpt-realtime-mini",
                                    input_seconds=len(pcm_data) / 48000.0 # 24kHz * 2 bytes = 48000 bytes per second
                                )

                                audio_buffer.clear()

                            # Plan next turn
                            await wait_for_user_transcript(current_input_item_id)
                            plan = await decide_next_turn_after_candidate_input()
                            if plan:
                                log_turn_state("VAD_SPEECH_STOPPED_APPLIED", {
                                    "answer_idx": answer_question_index,
                                    "next_plan": plan.to_log_dict()
                                })
                                await send_response_create_with_turn(plan)
                            else:
                                log_turn_state("VAD_SPEECH_STOPPED_APPLIED", {
                                    "answer_idx": answer_question_index,
                                    "next_plan": None
                                })

                        elif event_type == "input_audio_buffer.committed":
                            commit_pending = False
                            has_uncommitted_audio = False
                            committed_item_id = event.get("item_id")
                            if committed_item_id:
                                last_committed_item_id = committed_item_id
                            log_turn_state("COMMIT_OK", {
                                "item_id": committed_item_id,
                                "last_committed_item_id": last_committed_item_id
                            })

                        # Forward other events to client
                        elif event_type in ["response.completed", "conversation.item.created", "session.updated", "session.created"]:
                            await websocket.send_text(json.dumps(event))

                except Exception as e:
                    log_interview_event(
                        event_name="relay.openai_to_client.error",
                        interview_id=interview.id,
                        interview_token=token,
                        level=logging.ERROR,
                        source="api.realtime",
                        outcome="failed",
                        error_message=str(e),
                    )

            # Run relays concurrently
            await asyncio.gather(relay_client_to_openai(), relay_openai_to_client())

    except WebSocketDisconnect:
        log_interview_event(
            event_name="ws.disconnected",
            interview_id=interview.id,
            interview_token=token,
            source="api.realtime",
            outcome="success"
        )
    except Exception as e:
        log_interview_event(
            event_name="ws.error",
            interview_id=interview.id,
            interview_token=token,
            level=logging.ERROR,
            source="api.realtime",
            outcome="failed",
            error_message=str(e)
        )
        await websocket.close(code=1011)
    finally:
        interview_id_for_log = interview.id if "interview" in locals() else None
        logger.info("Interview ended: id=%s, token=%s", interview_id_for_log, token)

        # 2. Release token from active registry
        async with active_tokens_lock:
            if token in active_interview_tokens:
                active_interview_tokens.remove(token)

        # Ensure upstream websocket is closed on all paths
        if 'openai_ws' in locals() and openai_ws and not openai_ws.closed:
            await openai_ws.close()

        # Log final usage summary
        if 'usage_tracker' in locals():
            usage_tracker.log_summary()

        # Log final orchestrator stats
        if 'orchestrator' in locals():
            log_interview_event(
                event_name="orchestrator.stats",
                interview_id=interview_id_for_log,
                interview_token=token,
                source="turn_orchestrator",
                details=orchestrator.get_stats()
            )