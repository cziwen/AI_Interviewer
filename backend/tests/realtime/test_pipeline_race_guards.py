import unittest
from types import SimpleNamespace

from backend.app.services.realtime.audio_pipeline import AudioPipeline
from backend.app.services.realtime.session_runner import RealtimeSessionRunner
from backend.app.services.realtime.state import SessionState


class DummyUpstreamWebSocket:
    def __init__(self):
        self.sent = []

    async def send(self, payload: str):
        self.sent.append(payload)


class DummyWebSocket:
    async def send_text(self, _text: str):
        return None


class PipelineRaceGuardTests(unittest.IsolatedAsyncioTestCase):
    def test_audio_pipeline_ignores_too_short_segments(self):
        state = SessionState(
            interview_start_ts=0.0,
            time_budget_sec=600.0,
            main_count_target=1,
            followup_limit=1,
            clarify_limit=1,
            expected_duration=10,
        )
        audio = AudioPipeline(state)
        audio.on_speech_started("item_1")
        for _ in range(3):
            audio.audio_buffer.append(b"xx")
        segment = audio.on_speech_stopped("item_1")
        self.assertIsNone(segment)

    async def test_commit_guard_deduplicates_pending_commit(self):
        interview = SimpleNamespace(
            id=1,
            name="candidate",
            position="AI Engineer",
            question_set=[],
        )
        runner = RealtimeSessionRunner(DummyWebSocket(), "token", interview, None)
        runner._load_job_profile()
        runner._init_runtime_state()
        runner.upstream_ws = DummyUpstreamWebSocket()

        runner.state.has_uncommitted_audio = True
        first = await runner._commit_input_audio_once("test", "item_1")
        second = await runner._commit_input_audio_once("test", "item_1")

        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(len(runner.upstream_ws.sent), 1)


if __name__ == "__main__":
    unittest.main()
