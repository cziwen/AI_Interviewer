from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class StandardAsrEvent:
    kind: str
    item_id: Optional[str] = None
    transcript: str = ""
    audio_start_ms: int = 0
    audio_end_ms: int = 0
    error: Optional[dict[str, Any]] = None


class AsrAdapter:
    @staticmethod
    def normalize_event(raw_event: dict[str, Any]) -> Optional[StandardAsrEvent]:
        event_type = str(raw_event.get("type") or "")

        if event_type in {"input_audio_buffer.speech_started", "vad.speech_started", "speech_started"}:
            return StandardAsrEvent(
                kind="speech_started",
                item_id=raw_event.get("item_id"),
                audio_start_ms=int(raw_event.get("audio_start_ms") or 0),
            )

        if event_type in {"input_audio_buffer.speech_stopped", "vad.speech_stopped", "speech_stopped"}:
            return StandardAsrEvent(
                kind="speech_stopped",
                item_id=raw_event.get("item_id"),
                audio_end_ms=int(raw_event.get("audio_end_ms") or 0),
            )

        if event_type in {
            "conversation.item.input_audio_transcription.completed",
            "input_audio_transcription.completed",
            "transcript.completed",
        }:
            return StandardAsrEvent(
                kind="transcript_completed",
                item_id=raw_event.get("item_id"),
                transcript=str(raw_event.get("transcript") or raw_event.get("text") or ""),
            )

        if event_type in {"input_audio_buffer.committed", "input_audio.committed", "audio.committed"}:
            return StandardAsrEvent(kind="input_committed", item_id=raw_event.get("item_id"))

        if event_type in {"error", "response.error"}:
            return StandardAsrEvent(kind="error", error=raw_event.get("error", {}) or {})

        return None
