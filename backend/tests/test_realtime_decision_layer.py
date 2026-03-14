import unittest

from backend.app.api.realtime import (
    _decision_action_to_turn_kind,
    _parse_and_validate_decision,
)
from backend.app.services.realtime_turn_orchestrator import TurnKind


class TestRealtimeDecisionLayer(unittest.TestCase):
    def test_parse_valid_actions(self):
        for action in (
            "followup",
            "next_question",
            "answer_candidate_question",
            "clarify",
            "finish_interview",
        ):
            payload = f'{{"action":"{action}","reason":"ok"}}'
            parsed, err = _parse_and_validate_decision(payload)
            self.assertIsNone(err)
            self.assertEqual(parsed["action"], action)

    def test_parse_invalid_json(self):
        parsed, err = _parse_and_validate_decision("not json")
        self.assertIsNone(parsed)
        self.assertEqual(err, "invalid_json")

    def test_parse_invalid_action(self):
        parsed, err = _parse_and_validate_decision('{"action":"skip","reason":"x"}')
        self.assertIsNone(parsed)
        self.assertEqual(err, "invalid_action")

    def test_parse_missing_reason(self):
        parsed, err = _parse_and_validate_decision('{"action":"followup"}')
        self.assertIsNone(parsed)
        self.assertEqual(err, "missing_reason")

    def test_parse_action_not_allowed_by_scope(self):
        parsed, err = _parse_and_validate_decision(
            '{"action":"finish_interview","reason":"done"}',
            allowed_actions={"followup", "next_question"},
        )
        self.assertIsNone(parsed)
        self.assertEqual(err, "action_not_allowed")

    def test_parse_action_allowed_by_scope(self):
        parsed, err = _parse_and_validate_decision(
            '{"action":"next_question","reason":"need move on"}',
            allowed_actions={"next_question"},
        )
        self.assertIsNone(err)
        self.assertEqual(parsed["action"], "next_question")

    def test_action_to_turn_kind_mapping(self):
        self.assertEqual(_decision_action_to_turn_kind("followup"), TurnKind.FOLLOWUP_PROMPT)
        self.assertEqual(_decision_action_to_turn_kind("next_question"), TurnKind.MAIN_PROMPT)
        self.assertEqual(_decision_action_to_turn_kind("answer_candidate_question"), TurnKind.HR_REDIRECT_PROMPT)
        self.assertEqual(_decision_action_to_turn_kind("clarify"), TurnKind.REASK_PROMPT)
        self.assertEqual(_decision_action_to_turn_kind("finish_interview"), TurnKind.CLOSING_PROMPT)
        self.assertIsNone(_decision_action_to_turn_kind("unknown"))


if __name__ == "__main__":
    unittest.main()
