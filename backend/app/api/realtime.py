import json
import base64
import asyncio
import websockets
import wave
import io
from typing import Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy.orm import Session
from ..database import get_db
from ..models.interview import Interview, InterviewStatus
from ..models.job_profile import JobProfile
from ..models.answer import Answer
from ..config import settings
from ..utils.logger import logger
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

router = APIRouter()

OPENAI_REALTIME_URL = "wss://api.openai.com/v1/realtime?model=gpt-realtime-mini"

# 候选人长时间未回答时，等待多少秒后由 AI 重新提问或提醒
NO_RESPONSE_REASK_SECONDS = 18

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

@router.websocket("/ws/{token}")
async def realtime_interview_endpoint(websocket: WebSocket, token: str, db: Session = Depends(get_db)):
    interview = db.query(Interview).filter(Interview.link_token == token).first()
    if not interview:
        logger.warning(f"WebSocket connection attempt with invalid token: {token}")
        await websocket.close(code=4004)
        return

    await websocket.accept()
    logger.info(f"WebSocket connected for token: {token}, Candidate: {interview.name}")

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

    # Connect to OpenAI Realtime
    headers = {
        "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
        "OpenAI-Beta": "realtime=v1"
    }

    try:
        logger.info(f"Connecting to OpenAI Realtime for token: {token}")
        async with websockets.connect(OPENAI_REALTIME_URL, additional_headers=headers) as openai_ws:
            logger.info(f"OpenAI Realtime connection established for token: {token}")

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

            def log_turn_state(event: str, extra: dict = None):
                """Enhanced logging with turn context"""
                active_turn = orchestrator.get_active_turn()
                state = {
                    "event": event,
                    "token": token,
                    "stage": current_stage.value,
                    "q_order": current_main_question_order,
                    "q_completed": main_questions_completed,
                    "followups_used": followups_used_for_current,
                    "expected_reply": expected_candidate_reply_for,
                    "overtime": overtime_mode,
                    "ts": time.time() - interview_start_ts,
                    "turn_id": active_turn.turn_id if active_turn else None,
                    "turn_status": active_turn.status.value if active_turn else None
                }
                if extra:
                    state.update(extra)
                logger.info(f"INTERVIEW_STATE: {json.dumps(state, ensure_ascii=False)}")

            log_turn_state("INTERVIEW_SESSION_START", {
                "candidate": interview.name,
                "position": interview.position,
                "main_question_count": main_question_count,
                "main_count_target": main_count_target,
                "followup_limit": followup_limit,
                "expected_duration": expected_duration
            })

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

            def plan_next_turn_after_candidate_input() -> Optional[TurnPlan]:
                """Plan the next turn based on current state (not yet committed)"""
                nonlocal overtime_mode, overtime_closing_sent

                elapsed = time.time() - interview_start_ts
                elapsed_ratio = elapsed / time_budget_sec if time_budget_sec > 0 else 0

                # Check for overtime
                if elapsed >= time_budget_sec and not overtime_mode:
                    logger.info(f"Interview reached time budget ({elapsed:.1f}s). Entering overtime mode.")
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

                    # Check if all main questions are completed
                    if next_completed >= main_count_target:
                        # All main questions completed
                        return TurnPlan(
                            turn_kind=TurnKind.CLOSING_PROMPT,
                            stage_after_completion=InterviewStage.CLOSING,
                            question_order_after_completion=current_main_question_order,
                            expected_reply_after_completion=None,
                            control_instruction=build_closing_instruction(),
                            advance_main_completed=advance_main,
                            next_followups_used=0
                        )

                    # If we just got a main answer, consider followup
                    # BUT ONLY if we haven't used all followups for this question
                    elif (advance_main and
                          followups_used_for_current < followup_limit and
                          current_main_question_order > 0 and
                          expected_duration > 0 and
                          elapsed_ratio <= 0.95):
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

                    # If we just got a followup answer OR we can't do more followups
                    # Move to the next main question
                    elif expected_candidate_reply_for == "followup" or advance_main:
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

            async def send_response_create_with_turn(plan: TurnPlan):
                """Send response.create and create a turn"""
                nonlocal pending_plan, current_main_question_order

                if orchestrator.has_pending_turn():
                    logger.info("Skip response.create because previous turn is still pending.")
                    log_turn_state("AI_RESPONSE_CREATE_SKIPPED", {
                        "reason": "pending_turn",
                        "plan": plan.to_log_dict() if plan else None
                    })
                    return

                # Context Reset Logic
                if settings.REALTIME_CONTEXT_RESET_MODE == "per_main_question":
                    # If we are moving to a NEW main question, clear conversation history
                    is_new_main = (plan.turn_kind == TurnKind.MAIN_PROMPT and 
                                 plan.question_order_after_completion != current_main_question_order)
                    
                    if is_new_main:
                        logger.info(f"RESETTING_CONTEXT for new main question {plan.question_order_after_completion}")
                        log_turn_state("CONTEXT_RESET_START", {"target_q": plan.question_order_after_completion})
                        
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
                    logger.info(f"Interview natural end reached for token {token}")
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
                            logger.info(f"Client manually ended turn")
                            await commit_input_audio_once("client_end_turn")
                            plan = plan_next_turn_after_candidate_input()
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
                                logger.info(f"Frontend no-response timeout triggered re-ask")

                except Exception as e:
                    logger.error(f"Client to OpenAI relay error: {e}")

            async def relay_openai_to_client():
                nonlocal is_recording_segment, candidate_speaking, pending_plan
                nonlocal current_input_item_id, commit_pending, last_committed_item_id

                try:
                    async for message in openai_ws:
                        event = json.loads(message)
                        event_type = event.get("type")

                        # Log non-delta events
                        if event_type not in ["response.audio.delta", "response.audio_transcript.delta", "response.text.delta"]:
                            logger.info(f"OpenAI Event: {event_type} - {json.dumps(event)}")

                        # 1. Handle Audio/Text Deltas for UI
                        if event_type in ["response.audio.delta", "response.text.delta", "response.audio_transcript.delta"]:
                            # Handle response.audio.delta properly
                            if event_type == "response.audio.delta":
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
                        elif event_type == "response.done":
                            response = event.get("response", {})
                            response_id = response.get("id")
                            status = response.get("status")
                            status_details = response.get("status_details", {})
                            usage = response.get("usage")

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
                            logger.error(f"OpenAI Error: {json.dumps(event, indent=2)}")
                            err = event.get("error", {}) or {}

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
                            logger.info(f"VAD: Speech started (audio_start_ms: {audio_start_ms})")
                            log_turn_state("VAD_SPEECH_STARTED", {
                                "audio_start_ms": audio_start_ms
                            })
                            is_recording_segment = True
                            candidate_speaking = True
                            current_input_item_id = event.get("item_id")
                            audio_buffer.clear()

                        elif event_type == "input_audio_buffer.speech_stopped":
                            audio_end_ms = event.get("audio_end_ms", 0)

                            # Calculate speech duration based on audio buffer
                            # Note: audio_start_ms might not be in this event, check if we have it stored
                            speech_duration_ms = audio_end_ms - (audio_start_ms if 'audio_start_ms' in locals() else 0)

                            logger.info(f"VAD: Speech stopped (audio_end_ms: {audio_end_ms})")
                            log_turn_state("VAD_SPEECH_STOPPED_RAW", {
                                "audio_end_ms": audio_end_ms
                            })
                            is_recording_segment = False
                            candidate_speaking = False
                            current_input_item_id = event.get("item_id") or current_input_item_id

                            # Filter out very short audio segments (less than 500ms)
                            # Check by audio buffer size as a proxy
                            MIN_AUDIO_BUFFER_SIZE = 5  # Minimum number of chunks
                            if len(audio_buffer) < MIN_AUDIO_BUFFER_SIZE:
                                logger.info(f"Ignoring short speech segment (buffer size: {len(audio_buffer)} chunks)")
                                log_turn_state("VAD_SPEECH_STOPPED_IGNORED", {
                                    "reason": "too_short",
                                    "buffer_size": len(audio_buffer)
                                })
                                audio_buffer.clear()
                                continue

                            # Skip if we have a pending turn
                            if orchestrator.has_pending_turn():
                                logger.info("Ignore speech_stopped because turn is still pending.")
                                log_turn_state("VAD_SPEECH_STOPPED_IGNORED", {"reason": "turn_pending"})
                                audio_buffer.clear()
                                continue

                            await commit_input_audio_once("vad_speech_stopped", current_input_item_id)

                            # Save audio
                            answer_question_index = 0
                            if expected_candidate_reply_for in ("main", "followup") and current_main_question_order > 0:
                                answer_question_index = current_main_question_order

                            if audio_buffer:
                                pcm_data = b"".join(audio_buffer)
                                wav_data = pcm16_to_wav(pcm_data)

                                file_name = f"{token}_{answer_question_index}_{secrets.token_hex(4)}.wav"
                                file_path = os.path.join(settings.UPLOAD_DIR, file_name)
                                with open(file_path, "wb") as f:
                                    f.write(wav_data)

                                logger.info(f"VAD: Saved speech segment for question {answer_question_index}")

                                db_answer = Answer(
                                    interview_id=interview.id,
                                    question_index=answer_question_index,
                                    audio_url=file_path,
                                    transcript=None
                                )
                                db.add(db_answer)
                                db.commit()

                                audio_buffer.clear()

                            # Plan next turn
                            plan = plan_next_turn_after_candidate_input()
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
                    logger.error(f"OpenAI to Client relay error: {e}")

            # Run relays concurrently
            await asyncio.gather(relay_client_to_openai(), relay_openai_to_client())

    except WebSocketDisconnect:
        logger.info(f"Client disconnected: {token}")
    except Exception as e:
        logger.error(f"Realtime session error for token {token}: {e}")
        await websocket.close(code=1011)
    finally:
        # Log final orchestrator stats
        if 'orchestrator' in locals():
            logger.info(f"ORCHESTRATOR_STATS: {json.dumps(orchestrator.get_stats())}")