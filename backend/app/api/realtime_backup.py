import json
import base64
import asyncio
import websockets
import wave
import io
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
    TurnContext
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
    
    # Try to find a JobProfile that matches this interview's position
    # In a real scenario, we might have a job_profile_id on the Interview model
    # For now, we'll look it up by position_name or assume it was linked during creation
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

    # Connect to OpenAI Realtime
    headers = {
        "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
        "OpenAI-Beta": "realtime=v1"
    }

    try:
        logger.info(f"Connecting to OpenAI Realtime for token: {token}")
        async with websockets.connect(OPENAI_REALTIME_URL, additional_headers=headers) as openai_ws:
            logger.info(f"OpenAI Realtime connection established for token: {token}")
            # 1. Initialize session with instructions and tools
            # Format question list with references
            formatted_questions = []
            for q in interview.question_set:
                ref = q.get('reference')
                ref_text = f"（参考方向/要点：{ref}）" if ref else "（开放题，无固定参考方向）"
                formatted_questions.append(f"题目 {q['order_index']}：{q['question_text']} {ref_text}")
            
            questions_str = "\n".join(formatted_questions)

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
   - 请根据提供的“参考方向/要点”和“岗位背景信息”来判断候选人的回答是否完整。
   - 如果回答明显不完整或遗漏关键点，且时间允许，请使用简短的话语提示引导候选人补充。
7. **被打断处理**：如果候选人在你确认回答完整前提到新话题，先简短回应，然后提醒“我们先把刚才那个问题说完”。
8. **长时间未回答**：若你收到系统提示“候选人尚未回答”，请简短重复当前问题或礼貌提醒候选人作答（例如：“您可以先简单说说想法，不必紧张。”），不要换题。
9. **跑题引导（高优先级）**：
   - 如果候选人询问与本次能力评估无关的 HR 或公司类话题（如：薪资、福利、职级、假期、制度、团队文化、具体业务细节、公司发展等），请统一回复：“本次面试仅作为能力评估，关于公司文化、薪资、制度等其他话题后续会由 HR 或人工面试官为您处理。我们现在继续回到面试中。”
   - 回复后，请立即将话题拉回到当前的面试题目或流程中。
10. **面试结束提示**：在面试进入 closing 阶段并完成结语时，请务必包含以下提示：“本次面试到这里就结束了。您可以手动点击‘结束面试’按钮，系统也会在稍后自动为您提交。感谢您的参与！”
11. **语气与语言**：语气要专业、礼貌且富有同理心。整个过程请使用中文。

题目列表与参考方向：
{questions_str}
""",
                    "voice": "alloy",
                    "modalities": ["text", "audio"],
                    "input_audio_format": "pcm16",  # PCM16 is always 24kHz in OpenAI Realtime
                    "output_audio_format": "pcm16",  # PCM16 is always 24kHz in OpenAI Realtime
                    "input_audio_transcription": {
                        "model": "whisper-1"
                    },
                    "turn_detection": {
                        "type": "server_vad",
                        "threshold": 0.5,
                        "prefix_padding_ms": 300,
                        # 600ms 在真实语音里偏激进，容易把短停顿误判为结束并抢话
                        "silence_duration_ms": 1200,
                        # We run fully manual turn control to avoid double responses.
                        "create_response": False
                    },
                }
            }
            await openai_ws.send(json.dumps(init_event))
            await asyncio.sleep(0.5) # Give OpenAI some time to process session update

            # 2. Start the conversation by asking the first question
            first_question_event = {
                "type": "response.create",
                "response": {
                    "modalities": ["text", "audio"],
                    "instructions": "请开始面试，向候选人问好并请他进行简短的自我介绍。这是面试的第一步 (intro stage)。"
                }
            }
            await openai_ws.send(json.dumps(first_question_event))

            # Track current question index and audio buffer
            current_question_index = 0
            audio_buffer = []
            is_recording_segment = False
            last_transcript = ""

            # Runtime pacing states
            interview_start_ts = time.time()
            time_budget_sec = expected_duration * 60
            ordered_questions = sorted(
                interview.question_set or [],
                key=lambda q: q.get("order_index", 0),
            )
            main_count_target = min(main_question_count, len(ordered_questions))
            main_questions_completed = 0
            current_main_question_order = 0
            followups_used_for_current = 0
            overtime_mode = False
            overtime_closing_sent = False
            candidate_speaking = False
            natural_end_sent = False
            current_stage = "intro" # intro, qa, closing
            expected_candidate_reply_for = "intro" # intro, main, followup, None
            # First question is sent right above; wait for response.done before next response.create.
            model_response_pending = True
            commit_pending = False
            last_committed_item_id = None
            current_input_item_id = None

            def log_turn_state(event: str, extra: dict = None):
                state = {
                    "event": event,
                    "token": token,
                    "stage": current_stage,
                    "q_order": current_main_question_order,
                    "q_completed": main_questions_completed,
                    "followups_used": followups_used_for_current,
                    "expected_reply": expected_candidate_reply_for,
                    "overtime": overtime_mode,
                    "model_pending": model_response_pending,
                    "ts": time.time() - interview_start_ts
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
                    return "主问题列表已结束。请立即进入 closing 阶段并完成礼貌结语。"
                question_text = question.get("question_text", "").strip()
                reference = (question.get("reference") or "").strip()
                reference_hint = f"参考方向：{reference}。" if reference else "这是一道开放题。"
                return (
                    f"现在进入第 {order}/{main_count_target} 个主问题。"
                    f"你必须先明确提出这道主问题（不要继续停留在自我介绍追问）："
                    f"{question_text}。{reference_hint}"
                    "提问时请先说明“主问题第"
                    f"{order}"
                    "题”，并围绕该题作答。一次只问一个问题。"
                )

            def build_followup_instruction(order: int) -> str:
                question = get_main_question(order)
                question_text = (question or {}).get("question_text", "").strip()
                return (
                    f"请围绕刚才这个主问题做一次简短追问（第 {order} 题：{question_text}）。"
                    "追问要短、聚焦关键遗漏点，不要切换到新主问题。"
                )

            def build_closing_instruction() -> str:
                return (
                    "所有主问题已完成。请立即进入 closing 阶段，礼貌结束面试，"
                    "并务必包含以下提示："
                    "“本次面试到这里就结束了。您可以手动点击‘结束面试’按钮，"
                    "系统也会在稍后自动为您提交。感谢您的参与！”"
                    "结束后不要再提出新问题。"
                )

            async def send_response_create(instructions: str = None):
                nonlocal model_response_pending
                if model_response_pending:
                    logger.info("Skip response.create because previous response is still pending.")
                    log_turn_state("AI_RESPONSE_CREATE_SKIPPED", {"reason": "pending", "instructions": instructions[:100] if instructions else None})
                    return
                log_turn_state("AI_NEXT_TURN", {"instructions": instructions[:100] if instructions else None})
                response_payload = {"type": "response.create", "response": {}}
                if instructions:
                    response_payload["response"]["instructions"] = instructions
                await openai_ws.send(json.dumps(response_payload))
                model_response_pending = True

            async def commit_input_audio_once(reason: str, item_id: str = None):
                nonlocal commit_pending, last_committed_item_id
                resolved_item_id = item_id or current_input_item_id
                log_turn_state("COMMIT_ATTEMPT", {"reason": reason, "item_id": resolved_item_id})

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

            # Relay tasks
            async def relay_client_to_openai():
                nonlocal current_question_index, followups_used_for_current, current_stage, overtime_mode, overtime_closing_sent, candidate_speaking
                try:
                    async for message in websocket.iter_text():
                        data = json.loads(message)
                        if data.get("type") == "audio":
                            audio_data = data["audio"]
                            raw_audio = base64.b64decode(audio_data)
                            
                            # Only buffer if we are in a speech segment (detected by VAD)
                            if is_recording_segment:
                                audio_buffer.append(raw_audio)
                            
                            # Always relay to OpenAI for their VAD to work
                            audio_event = {
                                "type": "input_audio_buffer.append",
                                "audio": audio_data
                            }
                            await openai_ws.send(json.dumps(audio_event))
                        elif data.get("type") == "end_turn":
                            logger.info(f"Client manually ended turn for question {current_question_index}")
                            await commit_input_audio_once("client_end_turn")
                            await send_response_create()
                        elif data.get("type") == "no_response_timeout":
                            if current_stage in ("intro", "qa") and not overtime_mode and not candidate_speaking:
                                log_turn_state("NO_RESPONSE_TIMEOUT_TRIGGERED")
                                await send_response_create(
                                    "候选人尚未回答。请简短重复当前问题或礼貌提醒候选人作答（例如：您可以先简单说说想法。），不要换题。"
                                )
                                logger.info(
                                    f"Frontend no-response timeout ({NO_RESPONSE_REASK_SECONDS}s) triggered re-ask for token {token}"
                                )
                except Exception as e:
                    logger.error(f"Client to OpenAI relay error for token {token}: {e}")

            async def relay_openai_to_client():
                nonlocal current_question_index, is_recording_segment, last_transcript, main_questions_completed, current_main_question_order, followups_used_for_current, current_stage, overtime_mode, overtime_closing_sent, candidate_speaking, natural_end_sent, expected_candidate_reply_for, model_response_pending, commit_pending, last_committed_item_id, current_input_item_id
                try:
                    async for message in openai_ws:
                        event = json.loads(message)
                        event_type = event.get("type")
                        
                        # Log ALL events for deep debugging
                        # We exclude deltas from being logged as full JSON to avoid flooding.
                        if event_type in ["response.audio.delta", "response.audio_transcript.delta", "response.text.delta"]:
                            pass
                        else:
                            logger.info(f"OpenAI Event: {event_type} - {json.dumps(event)}")
                        
                        # 1. Handle Audio/Text Deltas for UI
                        if event_type in ["response.audio.delta", "response.text.delta", "response.audio_transcript.delta"]:
                            # Fix: For response.audio.delta, the audio data is in 'delta' field, not 'audio'
                            if event_type == "response.audio.delta":
                                # OpenAI sends audio in the 'delta' field for response.audio.delta
                                if "delta" in event:
                                    # Create a modified event with 'audio' field for frontend compatibility
                                    modified_event = event.copy()
                                    modified_event["audio"] = event["delta"]  # Move delta to audio field
                                    await websocket.send_text(json.dumps(modified_event))

                                    # Log for debugging
                                    audio_preview = event["delta"][:50] if event.get("delta") else "EMPTY"
                                    logger.debug(f"response.audio.delta forwarded, audio preview: {audio_preview}...")
                                else:
                                    logger.warning(f"response.audio.delta missing 'delta' field: {list(event.keys())}")
                                    await websocket.send_text(json.dumps(event))
                            else:
                                await websocket.send_text(json.dumps(event))

                            if event_type == "response.audio_transcript.delta":
                                last_transcript += event.get("delta", "")
                        
                        # 2. Handle Errors
                        elif event_type == "error":
                            logger.error(f"OpenAI Realtime Error for token {token}: {json.dumps(event, indent=2)}")
                            model_response_pending = False
                            err = event.get("error", {}) or {}
                            if err.get("code") == "input_audio_buffer_commit_empty":
                                commit_pending = False
                                log_turn_state("COMMIT_EMPTY_ERROR", {
                                    "error_code": err.get("code"),
                                    "error_message": err.get("message"),
                                    "item_id": current_input_item_id,
                                    "last_committed_item_id": last_committed_item_id
                                })
                        
                        # 3. Handle VAD Events for precise recording
                        elif event_type == "input_audio_buffer.speech_started":
                            logger.info(f"VAD: Speech started for question {current_question_index}")
                            log_turn_state("VAD_SPEECH_STARTED")
                            is_recording_segment = True
                            candidate_speaking = True
                            current_input_item_id = event.get("item_id")
                            audio_buffer.clear() # Start fresh for this segment
                            
                        elif event_type == "input_audio_buffer.speech_stopped":
                            logger.info(f"VAD: Speech stopped for question {current_question_index}")
                            log_turn_state("VAD_SPEECH_STOPPED_RAW")
                            is_recording_segment = False
                            candidate_speaking = False
                            current_input_item_id = event.get("item_id") or current_input_item_id
                            if model_response_pending:
                                logger.info("Ignore speech_stopped because model response is still pending.")
                                log_turn_state("VAD_SPEECH_STOPPED_IGNORED", {"reason": "model_pending"})
                                continue
                            await commit_input_audio_once("vad_speech_stopped", current_input_item_id)

                            # Handle pacing and overtime logic before OpenAI automatically responds
                            elapsed = time.time() - interview_start_ts
                            elapsed_ratio = elapsed / time_budget_sec if time_budget_sec > 0 else 0
                            
                            # Check for overtime
                            if elapsed >= time_budget_sec and not overtime_mode:
                                logger.info(f"Interview reached time budget ({elapsed:.1f}s). Entering overtime mode.")
                                overtime_mode = True
                            
                            # Check for hard timeout (20% or 5 minutes, whichever is greater)
                            hard_timeout_buffer = max(time_budget_sec * 0.2, 300)
                            if elapsed >= (time_budget_sec + hard_timeout_buffer):
                                logger.info(f"Interview reached hard timeout ({elapsed:.1f}s). Forcing close.")
                                # Send a final message and close
                                await send_response_create("面试时间已严重超时，请立即告知候选人面试必须结束，并直接进行结语。然后停止发言。")
                                # We'll let the response finish before closing the WS, or just close it after a short delay
                                # For now, we'll mark it for closing in the next turn or just let the AI finish the sentence.
                                # To be safe, we can wait a bit then close.
                                await asyncio.sleep(5) 
                                await websocket.close(code=1000, reason="Interview hard timeout")
                                return

                            # Capture user's input
                            answer_question_index = 0
                            if expected_candidate_reply_for in ("main", "followup") and current_main_question_order > 0:
                                answer_question_index = current_main_question_order
                            logger.info(
                                "TurnState stage=%s expected=%s main_order=%s completed=%s answer_idx=%s",
                                current_stage,
                                expected_candidate_reply_for,
                                current_main_question_order,
                                main_questions_completed,
                                answer_question_index,
                            )
                            if audio_buffer:
                                pcm_data = b"".join(audio_buffer)
                                wav_data = pcm16_to_wav(pcm_data)
                                
                                file_name = f"{token}_{answer_question_index}_{secrets.token_hex(4)}.wav"
                                file_path = os.path.join(settings.UPLOAD_DIR, file_name)
                                with open(file_path, "wb") as f:
                                    f.write(wav_data)
                                
                                logger.info(f"VAD: Saved speech segment for question {answer_question_index} to {file_path}")
                                
                                db_answer = Answer(
                                    interview_id=interview.id,
                                    question_index=answer_question_index,
                                    audio_url=file_path,
                                    transcript=None
                                )
                                db.add(db_answer)
                                db.commit()
                                
                                audio_buffer.clear()

                            # Determine next controlled response
                            control_instruction = ""
                            if overtime_mode:
                                if not overtime_closing_sent:
                                    control_instruction = (
                                        "面试时间已到。请不要再问新的主问题或追问，"
                                        "礼貌自然地结束面试。如果候选人刚才在提问，"
                                        "请简短回答后结束。进入 closing stage。"
                                    )
                                    overtime_closing_sent = True
                                    current_stage = "closing"
                                else:
                                    control_instruction = build_closing_instruction()
                                expected_candidate_reply_for = None
                            elif current_stage == "intro":
                                if main_count_target <= 0:
                                    current_stage = "closing"
                                    control_instruction = build_closing_instruction()
                                    expected_candidate_reply_for = None
                                else:
                                    current_stage = "qa"
                                    current_main_question_order = 1
                                    current_question_index = current_main_question_order
                                    followups_used_for_current = 0
                                    control_instruction = build_main_question_instruction(current_main_question_order)
                                    expected_candidate_reply_for = "main"
                            elif current_stage == "qa":
                                if expected_candidate_reply_for == "main":
                                    main_questions_completed += 1
                                expected_candidate_reply_for = None

                                if main_questions_completed >= main_count_target:
                                    current_stage = "closing"
                                    control_instruction = build_closing_instruction()
                                elif (
                                    followups_used_for_current < followup_limit
                                    and current_main_question_order > 0
                                    and expected_duration > 0
                                    and elapsed_ratio <= 0.95
                                ):
                                    followups_used_for_current += 1
                                    current_question_index = current_main_question_order
                                    control_instruction = build_followup_instruction(current_main_question_order)
                                    expected_candidate_reply_for = "followup"
                                else:
                                    current_main_question_order = main_questions_completed + 1
                                    current_question_index = current_main_question_order
                                    followups_used_for_current = 0
                                    control_instruction = build_main_question_instruction(current_main_question_order)
                                    expected_candidate_reply_for = "main"
                            elif current_stage == "closing":
                                # Closing stage should not ask new questions.
                                current_stage = "closing"
                                control_instruction = build_closing_instruction()
                                expected_candidate_reply_for = None

                            if control_instruction:
                                logger.info(f"Control instruction: {control_instruction}")
                                if expected_candidate_reply_for == "main":
                                    log_turn_state("MAIN_QUESTION_PROMPT_SENT", {
                                        "question_order": current_main_question_order,
                                        "question_preview": control_instruction[:120]
                                    })
                                log_turn_state("VAD_SPEECH_STOPPED_APPLIED", {
                                    "answer_idx": answer_question_index,
                                    "control_instruction": control_instruction[:100],
                                    "next_stage": current_stage
                                })
                                await send_response_create(control_instruction)
                            else:
                                log_turn_state("VAD_SPEECH_STOPPED_APPLIED", {
                                    "answer_idx": answer_question_index,
                                    "control_instruction": None,
                                    "next_stage": current_stage
                                })
                        
                        elif event_type == "response.done":
                            logger.info(f"OpenAI: Response done. Transcript: {last_transcript}")
                            model_response_pending = False
                            if expected_candidate_reply_for == "main" and current_stage == "qa":
                                aligned, matched_chunks = is_main_question_aligned(
                                    current_main_question_order,
                                    last_transcript
                                )
                                if not aligned:
                                    question = get_main_question(current_main_question_order) or {}
                                    log_turn_state("MAIN_QUESTION_DRIFT_DETECTED", {
                                        "expected_question_order": current_main_question_order,
                                        "expected_question_text": (question.get("question_text") or "")[:120],
                                        "actual_transcript_snippet": (last_transcript or "")[:120],
                                        "matched_chunks": matched_chunks
                                    })
                            log_turn_state("AI_RESPONSE_DONE", {"transcript_len": len(last_transcript)})
                            
                            # Check if we just finished the closing stage
                            if current_stage == "closing" and not natural_end_sent:
                                logger.info(f"Interview natural end reached for token {token}")
                                log_turn_state("INTERVIEW_NATURAL_END_SENT")
                                # Notify frontend about the natural end
                                await websocket.send_text(json.dumps({"type": "interview.natural_end"}))
                                natural_end_sent = True
                                # Give frontend a moment to receive the event before we potentially close
                                await asyncio.sleep(1)
                                # We don't close the websocket here to allow the frontend to handle the 15s countdown
                                # and call the /complete API. The frontend will close it.
                            last_transcript = ""
                            
                        elif event_type == "input_audio_buffer.committed":
                            commit_pending = False
                            committed_item_id = event.get("item_id")
                            if committed_item_id:
                                last_committed_item_id = committed_item_id
                            log_turn_state("COMMIT_OK", {
                                "item_id": committed_item_id,
                                "last_committed_item_id": last_committed_item_id
                            })

                        # Forward other useful events to client
                        elif event_type in ["response.created", "response.completed", "conversation.item.created", "session.updated", "session.created"]:
                            if event_type == "response.created":
                                model_response_pending = True
                                log_turn_state("AI_RESPONSE_CREATED", {"response_id": event.get("response", {}).get("id")})
                            await websocket.send_text(json.dumps(event))
                            
                except Exception as e:
                    logger.error(f"OpenAI to Client relay error for token {token}: {e}")

            # Run relays concurrently
            await asyncio.gather(relay_client_to_openai(), relay_openai_to_client())

    except WebSocketDisconnect:
        logger.info(f"Client disconnected: {token}")
    except Exception as e:
        logger.error(f"Realtime session error for token {token}: {e}")
        await websocket.close(code=1011)
