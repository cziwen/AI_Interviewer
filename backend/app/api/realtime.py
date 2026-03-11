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
import os
import secrets
import time

router = APIRouter()

OPENAI_REALTIME_URL = "wss://api.openai.com/v1/realtime?model=gpt-4o-mini-realtime-preview"

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
3. **候选人提问** (candidate_q)：主问题结束后，邀请候选人提问。
4. **自然结束** (closing)：礼貌地结束面试。

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
8. **语气与语言**：语气要专业、礼貌且富有同理心。整个过程请使用中文。

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
                        "silence_duration_ms": 600
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
            main_count_target = main_question_count
            main_questions_asked = 0
            followups_used_for_current = 0
            overtime_mode = False
            overtime_closing_sent = False
            candidate_speaking = False
            current_stage = "intro" # intro, qa, candidate_q, closing

            # Relay tasks
            async def relay_client_to_openai():
                nonlocal current_question_index
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
                            await openai_ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
                            await openai_ws.send(json.dumps({"type": "response.create"}))
                except Exception as e:
                    logger.error(f"Client to OpenAI relay error for token {token}: {e}")

            async def relay_openai_to_client():
                nonlocal current_question_index, is_recording_segment, last_transcript
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
                        
                        # 3. Handle VAD Events for precise recording
                        elif event_type == "input_audio_buffer.speech_started":
                            logger.info(f"VAD: Speech started for question {current_question_index}")
                            is_recording_segment = True
                            candidate_speaking = True
                            audio_buffer.clear() # Start fresh for this segment
                            
                        elif event_type == "input_audio_buffer.speech_stopped":
                            logger.info(f"VAD: Speech stopped for question {current_question_index}")
                            is_recording_segment = False
                            candidate_speaking = False
                            
                            # Automatically commit and create response on speech stopped (Voice Agent behavior)
                            # Note: In server_vad mode with create_response=true, OpenAI will automatically
                            # commit the buffer and create a response. We don't need to manually send these.
                            # await openai_ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
                            # await openai_ws.send(json.dumps({"type": "response.create"}))

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
                                force_close_event = {
                                    "type": "response.create",
                                    "response": {
                                        "instructions": "面试时间已严重超时，请立即告知候选人面试必须结束，并直接进行结语。然后停止发言。"
                                    }
                                }
                                await openai_ws.send(json.dumps(force_close_event))
                                # We'll let the response finish before closing the WS, or just close it after a short delay
                                # For now, we'll mark it for closing in the next turn or just let the AI finish the sentence.
                                # To be safe, we can wait a bit then close.
                                await asyncio.sleep(5) 
                                await websocket.close(code=1000, reason="Interview hard timeout")
                                return

                            # Determine pacing instructions
                            pacing_instruction = ""
                            if overtime_mode:
                                if not overtime_closing_sent:
                                    pacing_instruction = "面试时间已到。请不要再问新的主问题或追问，礼貌自然地结束面试。如果候选人刚才在提问，请简短回答后结束。进入 closing stage。"
                                    overtime_closing_sent = True
                                    current_stage = "closing"
                            else:
                                # Progress based pacing
                                q_progress = main_questions_asked / main_count_target if main_count_target > 0 else 1
                                if elapsed_ratio > q_progress + 0.1: # Falling behind
                                    pacing_instruction = "节奏落后：请减少或停止追问，尽快进入下一个主问题。"
                                elif current_stage == "intro" and elapsed > 120: # Intro taking too long (>2min)
                                    pacing_instruction = "自我介绍时间较长，请适时结束并进入第一个主问题 (qa stage)。"
                                
                                if main_questions_asked >= main_count_target and current_stage == "qa":
                                    pacing_instruction = "所有主问题已问完。请进入候选人提问环节 (candidate_q stage)。"
                                    current_stage = "candidate_q"

                            if pacing_instruction:
                                logger.info(f"Pacing: {pacing_instruction}")
                                # Send a session update or response create with pacing instructions
                                # Since OpenAI server_vad=true automatically creates a response, 
                                # we can try to send a session.update right before it starts generating, 
                                # or send a manual response.create if we want to override.
                                # A safer way in Realtime is to update session instructions or send a conversation item.
                                pacing_event = {
                                    "type": "response.create",
                                    "response": {
                                        "instructions": pacing_instruction
                                    }
                                }
                                await openai_ws.send(json.dumps(pacing_event))

                            # Capture user's input
                            if audio_buffer:
                                pcm_data = b"".join(audio_buffer)
                                wav_data = pcm16_to_wav(pcm_data)
                                
                                file_name = f"{token}_{current_question_index}_{secrets.token_hex(4)}.wav"
                                file_path = os.path.join(settings.UPLOAD_DIR, file_name)
                                with open(file_path, "wb") as f:
                                    f.write(wav_data)
                                
                                logger.info(f"VAD: Saved speech segment for question {current_question_index} to {file_path}")
                                
                                db_answer = Answer(
                                    interview_id=interview.id,
                                    question_index=current_question_index,
                                    audio_url=file_path,
                                    transcript=None
                                )
                                db.add(db_answer)
                                db.commit()
                                
                                audio_buffer.clear()
                        
                        elif event_type == "response.done":
                            logger.info(f"OpenAI: Response done. Transcript: {last_transcript}")
                            # Only increment question index if AI actually said something substantial
                            if len(last_transcript.strip()) > 5:
                                # Cap the question index at the number of questions in the set
                                max_questions = len(interview.question_set)
                                if current_question_index < max_questions:
                                    current_question_index += 1
                                    main_questions_asked += 1
                                    followups_used_for_current = 0
                                    if current_stage == "intro":
                                        current_stage = "qa"
                                else:
                                    # This might be a follow-up
                                    followups_used_for_current += 1
                            last_transcript = ""
                            
                        # Forward other useful events to client
                        elif event_type in ["response.created", "response.completed", "conversation.item.created", "session.updated", "session.created"]:
                            await websocket.send_text(json.dumps(event))
                            
                except Exception as e:
                    logger.error(f"OpenAI to Client relay error for token {token}: {e}")
                            
                except Exception as e:
                    logger.error(f"OpenAI to Client relay error for token {token}: {e}")

            # Run relays concurrently
            await asyncio.gather(relay_client_to_openai(), relay_openai_to_client())

    except WebSocketDisconnect:
        logger.info(f"Client disconnected: {token}")
    except Exception as e:
        logger.error(f"Realtime session error for token {token}: {e}")
        await websocket.close(code=1011)
