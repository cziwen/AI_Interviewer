import unittest

from backend.app.services.realtime_turn_orchestrator import (
    InterviewStage,
    RealtimeTurnOrchestrator,
    TurnKind,
    TurnPlan,
    TurnStatus,
)


class OrchestratorTransitionGuardTests(unittest.TestCase):
    def test_only_completed_turn_advances_business_state(self):
        orchestrator = RealtimeTurnOrchestrator("token", "candidate", "AI Engineer")
        plan = TurnPlan(
            turn_kind=TurnKind.MAIN_PROMPT,
            stage_after_completion=InterviewStage.QA,
            question_order_after_completion=1,
            expected_reply_after_completion="main",
            control_instruction="ask",
            advance_main_completed=False,
            next_followups_used=0,
        )
        turn = orchestrator.create_turn(
            plan=plan,
            current_stage=InterviewStage.INTRO,
            expected_reply_before="intro",
            question_order=0,
        )
        turn.status = TurnStatus.CANCELLED
        transition = orchestrator.create_business_transition(plan, turn)
        self.assertIsNone(transition)


if __name__ == "__main__":
    unittest.main()
