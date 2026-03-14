import asyncio
import unittest
from types import SimpleNamespace

from backend.app.services.realtime.session_runner import RealtimeSessionRunner


class DummyWebSocket:
    async def send_text(self, _text: str):
        return None


class PipelineOrderingTests(unittest.IsolatedAsyncioTestCase):
    def _build_runner(self) -> RealtimeSessionRunner:
        interview = SimpleNamespace(
            id=1,
            name="candidate",
            position="AI Engineer",
            question_set=[{"order_index": 1, "question_text": "Q1", "reference": "R1"}],
        )
        runner = RealtimeSessionRunner(
            websocket=DummyWebSocket(),
            token="token",
            interview=interview,
            job_profile=None,
        )
        runner._load_job_profile()
        runner._init_runtime_state()
        return runner

    async def test_finalize_is_linearized_by_decision_pending(self):
        runner = self._build_runner()
        calls = []

        async def fake_commit(_reason: str, _item_id=None):
            calls.append("commit")
            await asyncio.sleep(0.05)
            return True

        async def fake_wait(_item_id):
            calls.append("transcribe")
            await asyncio.sleep(0.05)
            return "ok"

        async def fake_decide():
            calls.append("decide")
            return None

        async def fake_send(_plan):
            calls.append("respond")
            return None

        runner._commit_input_audio_once = fake_commit  # type: ignore[method-assign]
        runner._wait_and_log_transcript = fake_wait  # type: ignore[method-assign]
        runner._decide_next_turn = fake_decide  # type: ignore[method-assign]
        runner._send_response_create_with_turn = fake_send  # type: ignore[method-assign]

        await asyncio.gather(
            runner._finalize_candidate_segment("t1", None, "item_1"),
            runner._finalize_candidate_segment("t2", None, "item_1"),
        )

        self.assertEqual(calls, ["commit", "transcribe", "decide", "commit", "transcribe", "decide"])


if __name__ == "__main__":
    unittest.main()
