import unittest

from backend.app.api.realtime import (
    _decision_action_to_turn_kind,
    _parse_and_validate_decision,
)
from backend.app.services.realtime.decision_engine import DecisionEngine
from backend.app.services.realtime_turn_orchestrator import InterviewStage, TurnKind


class TestRealtimeDecisionLayer(unittest.TestCase):
    def test_parse_valid_actions(self):
        for action in (
            "followup",
            "next_question",
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

    def test_parse_removed_answer_action_invalid(self):
        parsed, err = _parse_and_validate_decision(
            '{"action":"answer_candidate_question","reason":"user asked"}'
        )
        self.assertIsNone(parsed)
        self.assertEqual(err, "invalid_action")

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
        self.assertEqual(_decision_action_to_turn_kind("clarify"), TurnKind.REASK_PROMPT)
        self.assertEqual(_decision_action_to_turn_kind("finish_interview"), TurnKind.CLOSING_PROMPT)
        self.assertIsNone(_decision_action_to_turn_kind("unknown"))

    def test_allowed_actions_block_followup_and_clarify_after_caps(self):
        actions = DecisionEngine.get_allowed_actions(
            current_stage=InterviewStage.QA,
            main_count_target=3,
            main_questions_completed=1,
            current_main_question_order=2,
            followups_used_for_current=1,
            followup_limit=1,
            clarifies_used_for_current=1,
            clarify_limit=1,
        )
        self.assertNotIn("followup", actions)
        self.assertNotIn("clarify", actions)
        self.assertIn("next_question", actions)


if __name__ == "__main__":
    unittest.main()
