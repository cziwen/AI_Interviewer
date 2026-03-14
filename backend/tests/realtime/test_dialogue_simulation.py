import asyncio
import json
import os
import unittest
from types import SimpleNamespace

import websockets

from backend.app.services.realtime.session_runner import RealtimeSessionRunner
from backend.app.services.realtime_turn_orchestrator import InterviewStage, TurnKind, TurnPlan


class FakeClientWebSocket:
    def __init__(self, client_messages=None):
        self.client_messages = client_messages or []
        self.accepted = False
        self.sent_events = []

    async def accept(self):
        self.accepted = True

    async def send_text(self, text: str):
        self.sent_events.append(json.loads(text))

    async def iter_text(self):
        for message in self.client_messages:
            yield json.dumps(message)


class FakeOpenAIWebSocket:
    def __init__(self, incoming_events=None):
        self.incoming_events = list(incoming_events or [])
        self.sent_payloads = []
        self.closed = False
        self._iter_index = 0

    async def send(self, payload: str):
        self.sent_payloads.append(json.loads(payload))

    async def close(self):
        self.closed = True

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._iter_index >= len(self.incoming_events):
            raise StopAsyncIteration
        event = self.incoming_events[self._iter_index]
        self._iter_index += 1
        await asyncio.sleep(0)
        return json.dumps(event)


class DialogueSimulationTests(unittest.IsolatedAsyncioTestCase):
    def _build_runner(self) -> RealtimeSessionRunner:
        interview = SimpleNamespace(
            id=101,
            name="candidate",
            position="AI Engineer",
            question_set=[{"order_index": 1, "question_text": "请介绍一个你做过的Agent项目", "reference": "背景与效果"}],
        )
        runner = RealtimeSessionRunner(
            websocket=FakeClientWebSocket(),
            token="token_sim",
            interview=interview,
            job_profile=None,
        )
        runner._load_job_profile()
        runner._init_runtime_state()
        runner.openai_ws = FakeOpenAIWebSocket()
        return runner

    async def test_mock_linear_chain_finalize(self):
        runner = self._build_runner()
        runner.state.current_stage = InterviewStage.QA
        runner.state.current_main_question_order = 1
        runner.state.expected_candidate_reply_for = "main"
        runner.state.main_count_target = 1
        runner.state.main_questions_completed = 1
        runner.state.has_uncommitted_audio = True

        order = []

        async def fake_commit(reason: str, item_id=None):
            self.assertIn("linear_finalize", reason)
            order.append("commit")
            return True

        async def fake_wait(item_id):
            self.assertEqual(item_id, "item_linear_1")
            runner.transcript_store.set_user_transcript(item_id, "这是候选人针对主问题的完整回答")
            order.append("transcription")
            return "这是候选人针对主问题的完整回答"

        async def fake_send(plan: TurnPlan):
            self.assertEqual(plan.turn_kind, TurnKind.CLOSING_PROMPT)
            order.append("response_create")

        original_call_decision = runner.decision_engine.call_decision_llm
        original_commit = runner._commit_input_audio_once
        original_wait = runner._wait_and_log_transcript
        original_send = runner._send_response_create_with_turn

        async def wrapped_call_decision(context):
            order.append("decision")
            return {"action": "finish_interview", "reason": "all done"}, None, 1

        runner.decision_engine.call_decision_llm = wrapped_call_decision
        runner._commit_input_audio_once = fake_commit  # type: ignore[method-assign]
        runner._wait_and_log_transcript = fake_wait  # type: ignore[method-assign]
        runner._send_response_create_with_turn = fake_send  # type: ignore[method-assign]

        try:
            await runner._finalize_candidate_segment(
                trigger="vad_speech_stopped",
                segment_pcm=b"\x00" * 240,
                item_id="item_linear_1",
            )
        finally:
            runner.decision_engine.call_decision_llm = original_call_decision
            runner._commit_input_audio_once = original_commit  # type: ignore[method-assign]
            runner._wait_and_log_transcript = original_wait  # type: ignore[method-assign]
            runner._send_response_create_with_turn = original_send  # type: ignore[method-assign]

        self.assertEqual(order, ["commit", "transcription", "decision", "response_create"])
        self.assertFalse(runner.state.decision_pending)

    async def test_transition_applies_after_response_done(self):
        runner = self._build_runner()
        runner.state.current_stage = InterviewStage.QA
        runner.state.expected_candidate_reply_for = "main"
        runner.state.current_main_question_order = 1

        plan = TurnPlan(
            turn_kind=TurnKind.CLOSING_PROMPT,
            stage_after_completion=InterviewStage.CLOSING,
            question_order_after_completion=1,
            expected_reply_after_completion=None,
            control_instruction="closing",
            advance_main_completed=False,
            next_followups_used=0,
        )
        runner.state.pending_plan = plan
        runner.orchestrator.create_turn(
            plan=plan,
            current_stage=InterviewStage.QA,
            expected_reply_before="main",
            question_order=1,
        )
        runner.orchestrator.bind_response("resp_linear_done")
        runner.orchestrator.append_transcript_delta("resp_linear_done", "感谢参与，本次面试结束。")

        runner.openai_ws = FakeOpenAIWebSocket(
            incoming_events=[
                {
                    "type": "response.done",
                    "response": {
                        "id": "resp_linear_done",
                        "status": "completed",
                        "usage": {"input_tokens": 1, "output_tokens": 1},
                    },
                }
            ]
        )

        await runner._relay_openai_to_client()

        self.assertEqual(runner.state.current_stage, InterviewStage.CLOSING)
        self.assertIsNone(runner.state.pending_plan)


@unittest.skipUnless(os.getenv("RUN_REALTIME_SMOKE") == "1", "Set RUN_REALTIME_SMOKE=1 to run live OpenAI smoke test")
class RealtimeSmokeTests(unittest.IsolatedAsyncioTestCase):
    async def test_live_realtime_smoke(self):
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            self.skipTest("OPENAI_API_KEY is required")

        headers = {
            "Authorization": f"Bearer {api_key}",
            "OpenAI-Beta": "realtime=v1",
        }
        url = "wss://api.openai.com/v1/realtime?model=gpt-realtime-mini"

        async with websockets.connect(url, additional_headers=headers) as ws:
            await ws.send(
                json.dumps(
                    {
                        "type": "session.update",
                        "session": {
                            "modalities": ["text", "audio"],
                            "instructions": "You are a helpful assistant. Reply in one short sentence.",
                            "voice": "alloy",
                            "input_audio_format": "pcm16",
                            "output_audio_format": "pcm16",
                            "input_audio_transcription": {"model": "whisper-1"},
                            "turn_detection": {"type": "server_vad"},
                        },
                    }
                )
            )
            await ws.send(
                json.dumps(
                    {
                        "type": "conversation.item.create",
                        "item": {
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_text", "text": "Say hello in Chinese."}],
                        },
                    }
                )
            )
            await ws.send(
                json.dumps(
                    {
                        "type": "response.create",
                        "response": {"modalities": ["text"], "instructions": "Keep it short."},
                    }
                )
            )

            got_done = False
            async def listen():
                nonlocal got_done
                async for message in ws:
                    event = json.loads(message)
                    if event.get("type") == "response.done":
                        got_done = True
                        return
                    if event.get("type") == "error":
                        raise AssertionError(f"OpenAI realtime error: {event}")

            await asyncio.wait_for(listen(), timeout=20)
            self.assertTrue(got_done)


if __name__ == "__main__":
    unittest.main()
