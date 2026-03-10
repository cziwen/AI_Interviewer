import logging
import os
import json
import time
from typing import Optional, List, Dict, Any, Generator
import requests

logger = logging.getLogger(__name__)

class LLMProcessor:
    def __init__(self, api_url: str = "http://localhost:8000/api/realtime/voice_turn"):
        self.api_url = api_url

    def generate_response(
        self,
        text: str,
        interview_id: str,
        session_id: str,
        system_prompt: Optional[str] = None
    ) -> Generator[str, None, None]:
        """
        Calls the internal interview API to get the next response.
        """
        payload = {
            "interview_id": interview_id,
            "session_id": session_id,
            "text": text,
            "system_prompt": system_prompt
        }
        
        try:
            # For now, we assume the internal API might not be streaming yet, 
            # so we simulate a generator for compatibility with AudioProcessor.
            # In the future, this should call a streaming endpoint.
            response = requests.post(self.api_url, json=payload, timeout=30)
            response.raise_for_status()
            data = response.json()
            reply_text = data.get("reply_text", "")
            
            # Yield in small chunks to simulate streaming if needed, 
            # or just yield the whole thing if it's short.
            yield reply_text
            
        except Exception as e:
            logger.error(f"LLM Error: {e}")
            yield "Sorry, I encountered an error processing your request."
