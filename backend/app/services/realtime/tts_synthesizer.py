from __future__ import annotations

from typing import Optional

import openai

from ...config import settings


class TtsSynthesizer:
    def __init__(self, api_key: Optional[str]):
        self._client = (
            openai.AsyncOpenAI(api_key=api_key, base_url=settings.ARK_BASE_URL)
            if api_key else None
        )

    async def synthesize(self, text: str) -> bytes:
        payload = (text or "").strip()
        if not payload:
            return b""
        if not self._client:
            return b""

        try:
            response = await self._client.audio.speech.create(
                model=settings.ARK_TTS_MODEL,
                voice=settings.ARK_TTS_VOICE,
                input=payload,
                response_format="pcm",
            )
            if hasattr(response, "read"):
                data = response.read()
                return data if isinstance(data, (bytes, bytearray)) else bytes(data or b"")
            if isinstance(response, (bytes, bytearray)):
                return bytes(response)
            return bytes(response or b"")
        except Exception:
            return b""
