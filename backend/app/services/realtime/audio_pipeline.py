from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Optional

from .state import SessionState, PipelineStage


@dataclass
class CandidateSegment:
    item_id: Optional[str]
    pcm_data: bytes
    duration_ms: float


class AudioPipeline:
    MIN_AUDIO_BUFFER_SIZE = 5

    def __init__(self, state: SessionState):
        self.state = state
        self.audio_buffer: list[bytes] = []
        self.is_recording_segment = False

    def on_client_audio(self, audio_base64: str) -> bytes:
        raw_audio = base64.b64decode(audio_base64)
        self.state.has_uncommitted_audio = True
        if self.is_recording_segment:
            self.audio_buffer.append(raw_audio)
        return raw_audio

    def on_speech_started(self, item_id: Optional[str]) -> None:
        self.is_recording_segment = True
        self.state.candidate_speaking = True
        self.state.current_input_item_id = item_id
        self.state.pipeline_stage = PipelineStage.AUDIO_COLLECTING
        self.audio_buffer.clear()

    def on_speech_stopped(self, item_id: Optional[str]) -> Optional[CandidateSegment]:
        self.is_recording_segment = False
        self.state.candidate_speaking = False
        if item_id:
            self.state.current_input_item_id = item_id
        if len(self.audio_buffer) < self.MIN_AUDIO_BUFFER_SIZE:
            self.audio_buffer.clear()
            return None

        pcm_data = b"".join(self.audio_buffer)
        self.audio_buffer.clear()
        self.state.pipeline_stage = PipelineStage.COMMITTED
        return CandidateSegment(
            item_id=self.state.current_input_item_id,
            pcm_data=pcm_data,
            duration_ms=len(pcm_data) / 48.0,
        )
