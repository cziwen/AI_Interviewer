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
from ..models.answer import Answer
from ..config import settings
from ..utils.logger import logger
import os
import secrets

router = APIRouter()

OPENAI_REALTIME_URL = "wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview-2024-10-01"

def pcm16_to_wav(pcm_data: bytes, sample_rate: int = 16000, channels: int = 1) -> bytes:
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
            init_event = {
                "type": "session.update",
                "session": {
                    "instructions": f"""
你是一名专业的 AI 面试官。你正在面试候选人 {interview.name or '先生/女士'}，岗位是 {interview.position or '基础岗位'}。
你的任务是根据提供的题目列表进行面试。
题目列表：{json.dumps(interview.question_set, ensure_ascii=False)}

规则：
1. 每次只问一个问题。
2. 候选人回答后，你可以根据回答进行简短的追问或回应，然后引导进入下一个问题。
3. 语气要专业、礼貌且富有同理心。
4. 当所有题目都问完且候选人没有更多补充时，礼貌地结束面试。
5. 整个过程请使用中文。
""",
                    "voice": "alloy",
                    "input_audio_format": "pcm16",
                    "output_audio_format": "pcm16",
                    "turn_detection": {"type": "server_vad"},
                }
            }
            await openai_ws.send(json.dumps(init_event))
            await asyncio.sleep(0.5) # Give OpenAI some time to process session update

            # 2. Start the conversation by asking the first question
            first_question_event = {
                "type": "response.create",
                "response": {
                    "modalities": ["text", "audio"],
                    "instructions": "请开始面试，向候选人问好并提出第一个问题。请确保完整说出你的开场白和第一个问题。"
                }
            }
            await openai_ws.send(json.dumps(first_question_event))

            # Track current question index and audio buffer
            current_question_index = 0
            audio_buffer = []
            is_recording_segment = False
            last_transcript = ""

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
                        
                        # 1. Handle Audio/Text Deltas for UI
                        if event["type"] in ["response.audio.delta", "response.text.delta", "response.audio_transcript.delta"]:
                            await websocket.send_text(json.dumps(event))
                            if event["type"] == "response.audio_transcript.delta":
                                last_transcript += event["delta"]
                        
                        # 2. Handle Errors
                        elif event["type"] == "error":
                            logger.error(f"OpenAI Realtime Error for token {token}: {event.get('error')}")
                        
                        # 3. Handle VAD Events for precise recording
                        elif event["type"] == "input_audio_buffer.speech_started":
                            logger.info(f"VAD: Speech started for question {current_question_index}")
                            is_recording_segment = True
                            audio_buffer.clear() # Start fresh for this segment
                            
                        elif event["type"] == "input_audio_buffer.speech_stopped":
                            logger.info(f"VAD: Speech stopped for question {current_question_index}")
                            is_recording_segment = False
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
                        
                        elif event["type"] == "response.done":
                            logger.info(f"OpenAI: Response done. Transcript: {last_transcript}")
                            # Only increment question index if AI actually said something substantial
                            if len(last_transcript.strip()) > 5:
                                current_question_index += 1
                            last_transcript = ""
                            
                except Exception as e:
                    logger.error(f"OpenAI to Client relay error for token {token}: {e}")

            # Run relays concurrently
            await asyncio.gather(relay_client_to_openai(), relay_openai_to_client())

    except WebSocketDisconnect:
        logger.info(f"Client disconnected: {token}")
    except Exception as e:
        logger.error(f"Realtime session error for token {token}: {e}")
        await websocket.close(code=1011)
