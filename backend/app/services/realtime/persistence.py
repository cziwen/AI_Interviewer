from __future__ import annotations

import io
import logging
import os
import secrets
import wave
from typing import Optional

from ...config import settings
from ...database import SessionLocal
from ...models.answer import Answer
from ...utils.logger import log_interview_event


def pcm16_to_wav(pcm_data: bytes, sample_rate: int = 24000, channels: int = 1) -> bytes:
    with io.BytesIO() as wav_io:
        with wave.open(wav_io, "wb") as wav_file:
            wav_file.setnchannels(channels)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm_data)
        return wav_io.getvalue()


def persist_audio_and_answer_sync(
    pcm_data: bytes,
    interview_id: int,
    token: str,
    answer_question_index: int,
    transcript: Optional[str],
) -> str:
    db = SessionLocal()
    try:
        wav_data = pcm16_to_wav(pcm_data)
        file_name = f"{token}_{answer_question_index}_{secrets.token_hex(4)}.wav"
        file_path = os.path.join(settings.UPLOAD_DIR, file_name)
        with open(file_path, "wb") as file_obj:
            file_obj.write(wav_data)

        db_answer = Answer(
            interview_id=interview_id,
            question_index=answer_question_index,
            audio_url=file_path,
            transcript=transcript,
        )
        db.add(db_answer)
        db.commit()
        return file_path
    except Exception as exc:
        db.rollback()
        log_interview_event(
            event_name="answer.persist_failed",
            interview_id=interview_id,
            interview_token=token,
            level=logging.ERROR,
            source="api.realtime",
            outcome="failed",
            error_message=str(exc),
            details={"question_index": answer_question_index},
        )
        raise
    finally:
        db.close()
