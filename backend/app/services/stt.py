import openai
from ..config import settings

async def transcribe_audio(audio_file_path: str) -> str:
    """
    使用 OpenAI Whisper API 进行音频转写。
    """
    if not settings.OPENAI_API_KEY:
        return "OpenAI API Key not configured."
        
    client = openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    
    try:
        with open(audio_file_path, "rb") as audio_file:
            transcript = await client.audio.transcriptions.create(
                model=settings.STT_MODEL,
                file=audio_file,
                response_format="text"
            )
            return transcript
    except Exception as e:
        print(f"STT error for {audio_file_path}: {e}")
        return f"[STT Error: {str(e)}]"
