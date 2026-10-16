import unittest

from app.efficientad.evaluation import evaluate_scores, select_threshold


class EfficientADEvaluationTests(unittest.TestCase):
    def test_threshold_uses_validation_scores(self) -> None:
        threshold = select_threshold([0.1, 0.2, 0.9, 1.0], [0, 0, 1, 1])
        report = evaluate_scores([0.1, 0.2, 0.9, 1.0], [0, 0, 1, 1], threshold, "validation")
        self.assertEqual(report.auroc, 1.0)
        self.assertEqual(report.f1, 1.0)

    def test_single_class_auroc_is_explicitly_unavailable(self) -> None:
        report = evaluate_scores([0.1, 0.2], [0, 0], 0.5, "test")
        self.assertIsNone(report.auroc)
