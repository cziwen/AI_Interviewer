from __future__ import annotations

import asyncio
import time
from typing import Optional

from ..realtime_turn_orchestrator import RealtimeTurnOrchestrator


class TranscriptStore:
    def __init__(self, orchestrator: RealtimeTurnOrchestrator):
        self._orchestrator = orchestrator

    def set_user_transcript(self, item_id: str, transcript: str) -> None:
        self._orchestrator.set_user_transcript(item_id, transcript)

    def get_user_transcript(self, item_id: Optional[str]) -> str:
        if not item_id:
            return ""
        return self._orchestrator.get_user_transcript(item_id) or ""

    async def wait_for_user_transcript(
        self,
        item_id: Optional[str],
        timeout_ms: int = 1200,
        poll_ms: int = 50,
    ) -> tuple[str, int]:
        if not item_id:
            return "", 0
        existing = self.get_user_transcript(item_id)
        if existing:
            return existing, 0

        start = time.time()
        deadline = start + (max(timeout_ms, 0) / 1000.0)
        poll_sec = max(poll_ms, 10) / 1000.0
        while time.time() < deadline:
            await asyncio.sleep(poll_sec)
            transcript = self.get_user_transcript(item_id)
            if transcript:
                waited_ms = int((time.time() - start) * 1000)
                return transcript, waited_ms

        waited_ms = int((time.time() - start) * 1000)
        return "", waited_ms
