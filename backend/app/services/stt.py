import openai
import wave
import contextlib
from ..config import settings

async def transcribe_audio(audio_file_path: str) -> tuple[str, float]:
    """
    使用火山方舟 STT API 进行音频转写。
    返回 (transcript, duration_seconds)
    """
    duration = 0.0
    try:
        with contextlib.closing(wave.open(audio_file_path, 'r')) as f:
            frames = f.getnframes()
            rate = f.getframerate()
            duration = frames / float(rate)
    except Exception as e:
        print(f"Error getting audio duration for {audio_file_path}: {e}")

    if not settings.ARK_API_KEY:
        return "ARK API Key not configured.", duration
        
    client = openai.AsyncOpenAI(
        api_key=settings.ARK_API_KEY,
        base_url=settings.ARK_BASE_URL,
    )
    
    try:
        with open(audio_file_path, "rb") as audio_file:
            transcript = await client.audio.transcriptions.create(
                model=settings.ARK_STT_MODEL,
                file=audio_file,
                response_format="text"
            )
            return transcript, duration
    except Exception as e:
        print(f"STT error for {audio_file_path}: {e}")
        return f"[STT Error: {str(e)}]", duration
