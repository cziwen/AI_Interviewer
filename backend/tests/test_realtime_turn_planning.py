import unittest
from unittest.mock import MagicMock, patch
import time
import re

# Mock settings class to avoid pydantic_settings dependency in test
class MockSettings:
    def __init__(self):
        self.REALTIME_MIN_MAIN_ANSWER_CHARS = 12
        self.REALTIME_MAIN_ANSWER_CONFIRM_WORDS = "嗯,好,可以,是的,明白,了解,好的,没问题,OK,ok"

settings = MockSettings()

# Mock Enums to avoid imports
class InterviewStage:
    QA = "qa"
    CLOSING = "closing"

class TurnKind:
    FOLLOWUP_PROMPT = "followup_prompt"
    CLOSING_PROMPT = "closing_prompt"
    REASK_PROMPT = "reask_prompt"
    MAIN_PROMPT = "main_prompt"

class TestRealtimeTurnPlanning(unittest.TestCase):
    def setUp(self):
        self.orchestrator = MagicMock()
        self.orchestrator.get_user_transcript.return_value = "这是一个非常详细的回答，超过了十二个字符。"
        
        # Initial state variables as they appear in the closure of realtime_interview_endpoint
        self.main_questions_completed = 0
        self.current_main_question_order = 1
        self.followups_used_for_current = 0
        self.main_count_target = 2
        self.followup_limit = 1
        self.expected_duration = 10
        self.interview_start_ts = time.time()
        self.time_budget_sec = self.expected_duration * 60
        self.current_stage = InterviewStage.QA
        self.expected_candidate_reply_for = "main"
        self.current_input_item_id = "item_1"

    def plan_next_turn(self):
        # Simplified version of the logic in realtime.py for testing
        elapsed = time.time() - self.interview_start_ts
        elapsed_ratio = elapsed / self.time_budget_sec if self.time_budget_sec > 0 else 0

        if self.current_stage == InterviewStage.QA:
            advance_main = (self.expected_candidate_reply_for == "main")
            next_completed = self.main_questions_completed + (1 if advance_main else 0)

            can_followup = (
                advance_main and
                self.followups_used_for_current < self.followup_limit and
                self.current_main_question_order > 0 and
                self.expected_duration > 0 and
                elapsed_ratio <= 0.95
            )

            if can_followup:
                return "FOLLOWUP_PROMPT", self.current_main_question_order, self.followups_used_for_current + 1

            if next_completed >= self.main_count_target:
                if advance_main:
                    user_transcript = self.orchestrator.get_user_transcript(self.current_input_item_id)
                    is_substantive = True
                    if not user_transcript:
                        is_substantive = False
                    else:
                        clean_text = re.sub(r"[，。！？；、,.!?;:\s（）()]+", "", user_transcript)
                        if len(clean_text) < settings.REALTIME_MIN_MAIN_ANSWER_CHARS:
                            is_substantive = False
                        confirm_words = [w.strip() for w in settings.REALTIME_MAIN_ANSWER_CONFIRM_WORDS.split(",") if w.strip()]
                        if clean_text in confirm_words:
                            is_substantive = False
                    
                    if not is_substantive:
                        return "REASK_PROMPT", self.current_main_question_order, self.followups_used_for_current

                return "CLOSING_PROMPT", self.current_main_question_order, 0

            if self.expected_candidate_reply_for == "followup" or advance_main:
                next_order = next_completed + 1
                return "MAIN_PROMPT", next_order, 0
        
        return None, None, None

    def map_decision_action(self, action: str):
        """Simplified decision mapping with finish_interview hard gate."""
        if action == "finish_interview":
            if self.main_count_target > 0 and self.main_questions_completed < self.main_count_target:
                next_order = min(self.main_questions_completed + 1, self.main_count_target)
                return "MAIN_PROMPT", next_order, 0
            else:
                return "CLOSING_PROMPT", self.current_main_question_order, 0

        if action == "next_question":
            advance_main = (self.expected_candidate_reply_for == "main")
            next_completed = self.main_questions_completed + (1 if advance_main else 0)
            if next_completed >= self.main_count_target:
                return "CLOSING_PROMPT", self.current_main_question_order, 0
            next_order = next_completed + 1
            return "MAIN_PROMPT", next_order, 0

        return None, None, None

    def test_last_question_followup_first(self):
        """Test that the last question gets a followup before closing"""
        self.main_questions_completed = 1
        self.current_main_question_order = 2 # Last question
        self.followups_used_for_current = 0
        self.expected_candidate_reply_for = "main"
        
        kind, order, next_followups = self.plan_next_turn()
        
        self.assertEqual(kind, "FOLLOWUP_PROMPT")
        self.assertEqual(order, 2)
        self.assertEqual(next_followups, 1)

    def test_last_question_closing_after_followup(self):
        """Test that after followup, it proceeds to closing"""
        self.main_questions_completed = 2 # Already advanced by followup logic in real code
        self.current_main_question_order = 2
        self.followups_used_for_current = 1 # Followup already used
        self.expected_candidate_reply_for = "followup"
        
        kind, order, next_followups = self.plan_next_turn()
        
        self.assertEqual(kind, "CLOSING_PROMPT")
        self.assertEqual(order, 2)

    def test_answer_gate_blocks_closing_on_short_answer(self):
        """Test that a short answer on the last question triggers a REASK instead of closing"""
        self.main_questions_completed = 1
        self.current_main_question_order = 2 # Last question
        self.followups_used_for_current = 1 # No more followups
        self.expected_candidate_reply_for = "main"
        self.orchestrator.get_user_transcript.return_value = "好的" # Too short
        
        kind, order, next_followups = self.plan_next_turn()
        
        self.assertEqual(kind, "REASK_PROMPT")
        self.assertEqual(order, 2)

    def test_answer_gate_allows_closing_on_long_answer(self):
        """Test that a substantive answer on the last question allows closing"""
        self.main_questions_completed = 1
        self.current_main_question_order = 2 # Last question
        self.followups_used_for_current = 1 # No more followups
        self.expected_candidate_reply_for = "main"
        self.orchestrator.get_user_transcript.return_value = "这是一个非常详细的回答，肯定超过了门槛。"
        
        kind, order, next_followups = self.plan_next_turn()
        
        self.assertEqual(kind, "CLOSING_PROMPT")
        self.assertEqual(order, 2)

    def test_finish_interview_blocked_before_target(self):
        """finish_interview should be blocked and rerouted to next question when target not met."""
        self.main_questions_completed = 1
        self.main_count_target = 2
        self.current_main_question_order = 1
        self.expected_candidate_reply_for = "main"

        kind, order, next_followups = self.map_decision_action("finish_interview")

        self.assertEqual(kind, "MAIN_PROMPT")
        self.assertEqual(order, 2)
        self.assertEqual(next_followups, 0)

    def test_finish_interview_allowed_after_target(self):
        """finish_interview should be allowed when all main questions are complete."""
        self.main_questions_completed = 2
        self.main_count_target = 2
        self.current_main_question_order = 2
        self.expected_candidate_reply_for = "followup"

        kind, order, next_followups = self.map_decision_action("finish_interview")

        self.assertEqual(kind, "CLOSING_PROMPT")
        self.assertEqual(order, 2)
        self.assertEqual(next_followups, 0)

if __name__ == "__main__":
    unittest.main()
