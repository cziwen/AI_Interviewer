# Realtime Backend Test Harness

This directory contains fast backend-only tests for realtime dialogue logic.

## Quick Run (Mock-Only, Recommended)

Run the dialogue simulation script:

`python -m unittest backend.tests.realtime.test_dialogue_simulation`

Run the full realtime backend regression set:

`python -m unittest backend.tests.test_realtime_decision_layer backend.tests.test_realtime_turn_planning backend.tests.realtime.test_pipeline_ordering backend.tests.realtime.test_pipeline_race_guards backend.tests.realtime.test_orchestrator_transition_guards backend.tests.realtime.test_dialogue_simulation backend.tests.realtime.test_upstream_event_adapter backend.tests.realtime.test_audio_chunker`

## Optional Live Smoke

Run a lightweight real ARK connectivity smoke test:

`RUN_REALTIME_SMOKE=1 python -m unittest backend.tests.realtime.test_dialogue_simulation`

Requirements:

- `ARK_API_KEY` is set in environment.
- Internet access is available.

## Pass Criteria

- Mock simulation preserves the linear chain:
  - commit -> transcription -> decision -> backend generate+tts
- Business transition applies after本地 `response.done(completed)` 发送。
- No duplicate pipeline advancement under concurrent finalize triggers.
