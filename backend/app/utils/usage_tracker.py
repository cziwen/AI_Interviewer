from dataclasses import dataclass, field
from typing import Dict, Any, Optional
from ..utils.logger import log_interview_event

@dataclass
class ModelUsage:
    text_input_tokens: int = 0
    text_output_tokens: int = 0
    audio_input_seconds: float = 0.0
    audio_output_seconds: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        res = {}
        if self.text_input_tokens > 0:
            res["text_input_tokens"] = self.text_input_tokens
        if self.text_output_tokens > 0:
            res["text_output_tokens"] = self.text_output_tokens
        if self.audio_input_seconds > 0:
            res["audio_input_seconds"] = round(self.audio_input_seconds, 2)
        if self.audio_output_seconds > 0:
            res["audio_output_seconds"] = round(self.audio_output_seconds, 2)
        return res

class InterviewUsageTracker:
    def __init__(self, interview_id: Optional[int] = None, interview_token: Optional[str] = None):
        self.interview_id = interview_id
        self.interview_token = interview_token
        self.usage_by_model: Dict[str, ModelUsage] = {}

    def _get_model_usage(self, model_name: str) -> ModelUsage:
        if model_name not in self.usage_by_model:
            self.usage_by_model[model_name] = ModelUsage()
        return self.usage_by_model[model_name]

    def add_text_usage(self, model_name: str, input_tokens: int = 0, output_tokens: int = 0):
        usage = self._get_model_usage(model_name)
        usage.text_input_tokens += input_tokens
        usage.text_output_tokens += output_tokens

    def add_audio_usage(self, model_name: str, input_seconds: float = 0.0, output_seconds: float = 0.0):
        usage = self._get_model_usage(model_name)
        usage.audio_input_seconds += input_seconds
        usage.audio_output_seconds += output_seconds

    def get_summary(self) -> Dict[str, Any]:
        return {
            model: usage.to_dict()
            for model, usage in self.usage_by_model.items()
            if usage.to_dict()
        }

    def log_summary(self):
        summary = self.get_summary()
        if not summary:
            return
            
        log_interview_event(
            event_name="interview.usage_summary",
            interview_id=self.interview_id,
            interview_token=self.interview_token,
            source="usage_tracker",
            details={"models": summary}
        )
