import math
import unittest

from app.policy import (
    DecisionPolicy,
    InspectionInput,
    ModelEvidence,
    Outcome,
    ReasonCode,
)


class DecisionPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = DecisionPolicy(
            version="policy-test-v1",
            compatible_model_versions=frozenset({"model-test-v1"}),
            pass_threshold=0.20,
            fail_threshold=0.80,
        )

    def evidence(self, score: float | None, *, available: bool = True, version: str | None = "model-test-v1") -> ModelEvidence:
        return ModelEvidence(model_version=version, score=score, available=available)

    def test_lower_boundary_is_pass(self) -> None:
        decision = self.policy.evaluate(InspectionInput(), self.evidence(0.20))
        self.assertEqual(decision.outcome, Outcome.PASS)

    def test_upper_boundary_is_fail(self) -> None:
        decision = self.policy.evaluate(InspectionInput(), self.evidence(0.80))
        self.assertEqual(decision.outcome, Outcome.FAIL)

    def test_review_band_is_unverified(self) -> None:
        decision = self.policy.evaluate(InspectionInput(), self.evidence(0.50))
        self.assertEqual(decision.outcome, Outcome.UNVERIFIED)
        self.assertEqual(decision.reason_codes, (ReasonCode.MODEL_SCORE_IN_REVIEW_BAND,))

    def test_invalid_image_is_unverified_without_score(self) -> None:
        decision = self.policy.evaluate(InspectionInput(valid=False), self.evidence(0.01))
        self.assertEqual(decision.outcome, Outcome.UNVERIFIED)
        self.assertEqual(decision.reason_codes, (ReasonCode.IMAGE_INVALID,))

    def test_stale_frame_is_unverified(self) -> None:
        decision = self.policy.evaluate(InspectionInput(stale=True), self.evidence(0.01))
        self.assertEqual(decision.reason_codes, (ReasonCode.FRAME_STALE,))

    def test_unavailable_model_is_never_pass(self) -> None:
        decision = self.policy.evaluate(InspectionInput(), self.evidence(None, available=False))
        self.assertEqual(decision.outcome, Outcome.UNVERIFIED)
        self.assertEqual(decision.reason_codes, (ReasonCode.MODEL_NOT_READY,))

    def test_invalid_model_outputs_are_unverified(self) -> None:
        for score in (None, math.nan, math.inf, -math.inf):
            with self.subTest(score=score):
                decision = self.policy.evaluate(InspectionInput(), self.evidence(score))
                self.assertEqual(decision.outcome, Outcome.UNVERIFIED)
                self.assertEqual(decision.reason_codes, (ReasonCode.MODEL_OUTPUT_INVALID,))

    def test_incompatible_model_is_unverified(self) -> None:
        decision = self.policy.evaluate(InspectionInput(), self.evidence(0.01, version="other"))
        self.assertEqual(decision.reason_codes, (ReasonCode.MODEL_VERSION_INCOMPATIBLE,))

    def test_invalid_threshold_order_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            DecisionPolicy("bad", frozenset({"model-test-v1"}), 0.8, 0.2)


if __name__ == "__main__":
    unittest.main()
