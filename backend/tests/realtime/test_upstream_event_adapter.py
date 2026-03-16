import unittest
from types import SimpleNamespace

from backend.app.services.realtime.session_runner import RealtimeSessionRunner


class DummyWebSocket:
    async def send_text(self, _text: str):
        return None


class UpstreamEventAdapterTests(unittest.TestCase):
    def _build_runner(self) -> RealtimeSessionRunner:
        interview = SimpleNamespace(
            id=1,
            name="candidate",
            position="AI Engineer",
            question_set=[],
        )
        runner = RealtimeSessionRunner(DummyWebSocket(), "token", interview, None)
        runner._load_job_profile()
        runner._init_runtime_state()
        return runner

    def test_speech_started_normalization(self):
        runner = self._build_runner()
        normalized = runner._normalize_upstream_event({"type": "speech_started", "item_id": "it_0", "audio_start_ms": 12})
        self.assertEqual(normalized.kind, "speech_started")
        self.assertEqual(normalized.item_id, "it_0")
        self.assertEqual(normalized.audio_start_ms, 12)

    def test_transcript_completed_normalization(self):
        runner = self._build_runner()
        normalized = runner._normalize_upstream_event(
            {"type": "transcript.completed", "item_id": "it_1", "text": "你好"}
        )
        self.assertEqual(normalized.kind, "transcript_completed")
        self.assertEqual(normalized.item_id, "it_1")
        self.assertEqual(normalized.transcript, "你好")

    def test_error_normalization(self):
        runner = self._build_runner()
        normalized = runner._normalize_upstream_event(
            {"type": "response.error", "error": {"code": "bad_request"}}
        )
        self.assertEqual(normalized.kind, "error")
        self.assertEqual(normalized.error["code"], "bad_request")

    def test_unknown_event_returns_none(self):
        runner = self._build_runner()
        normalized = runner._normalize_upstream_event({"type": "unknown.event"})
        self.assertIsNone(normalized)


if __name__ == "__main__":
    unittest.main()
