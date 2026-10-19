import unittest
import csv
import json
import tempfile
from pathlib import Path

from app.efficientad.data import DatasetManifest, ManifestRow
from app.efficientad.evaluation import (
    CostConfig,
    ReviewBand,
    calibrate_threshold,
    compare_score_csvs,
    evaluate_scores,
    select_threshold,
    write_evidence,
)


class EfficientADEvaluationTests(unittest.TestCase):
    @staticmethod
    def _row(identifier: str, split: str, label: int, digest: str) -> ManifestRow:
        return ManifestRow(
            identifier=identifier, path=f"{identifier}.png", category="bottle", label=label,
            defect_type=None, physical_sample_id=None, capture_session=None, camera_id=None,
            width=4, height=4, split=split, mask_path=None, sha256=digest,
        )

    def test_threshold_uses_validation_scores(self) -> None:
        threshold = select_threshold([0.1, 0.2, 0.9, 1.0], [0, 0, 1, 1])
        report = evaluate_scores([0.1, 0.2, 0.9, 1.0], [0, 0, 1, 1], threshold, "validation")
        self.assertEqual(report.auroc, 1.0)
        self.assertEqual(report.f1, 1.0)

    def test_single_class_auroc_is_explicitly_unavailable(self) -> None:
        report = evaluate_scores([0.1, 0.2], [0, 0], 0.5, "test")
        self.assertIsNone(report.auroc)

    def test_costs_choose_validation_threshold_and_report_operational_rates(self) -> None:
        threshold = select_threshold([0.1, 0.4, 0.5, 0.9], [0, 0, 1, 1], costs=CostConfig(false_accept_cost=10, false_reject_cost=1))
        self.assertEqual(threshold, 0.5)
        report = evaluate_scores([0.1, 0.4, 0.5, 0.9], [0, 0, 1, 1], threshold, "test")
        self.assertEqual((report.true_positive, report.false_positive, report.true_negative, report.false_negative), (2, 0, 2, 0))
        self.assertEqual(report.false_rejection_normal, 0.0)
        self.assertEqual(report.missed_defect_rate, 0.0)

    def test_review_band_is_explicitly_counted(self) -> None:
        policy = calibrate_threshold([0.1, 0.9], [0, 1], review_band=ReviewBand(0.4, 0.6))
        report = evaluate_scores([0.5, 0.9], [0, 1], policy.threshold, "test", policy=policy)
        self.assertEqual(report.review_count, 1)
        self.assertEqual(report.false_positive, 0)

    def test_csv_comparison_locks_manifest_and_serializes_evidence(self) -> None:
        rows = (
            self._row("train", "train", 0, "a"),
            self._row("v-good", "validation", 0, "b"),
            self._row("v-bad", "validation", 1, "c"),
            self._row("t-good", "test", 0, "d"),
            self._row("t-bad", "test", 1, "e"),
        )
        manifest = DatasetManifest(Path("."), rows)
        with tempfile.TemporaryDirectory() as directory:
            def write(name, values):
                path = Path(directory) / name
                with path.open("w", newline="", encoding="utf-8") as stream:
                    writer = csv.writer(stream)
                    writer.writerow(["sample_id", "score", "latency_ms", "model_size_bytes"])
                    writer.writerows(values)
                return path
            baseline = write("baseline.csv", [("train", .1, 3, 10), ("v-good", .2, 3, 10), ("v-bad", .8, 3, 10), ("t-good", .1, 3, 10), ("t-bad", .9, 3, 10)])
            adapted = write("adapted.csv", [("train", .1, 4, 20), ("v-good", .3, 4, 20), ("v-bad", .7, 4, 20), ("t-good", .2, 4, 20), ("t-bad", .8, 4, 20)])
            evidence = compare_score_csvs(manifest, baseline, adapted, costs=CostConfig(2, 3))
            self.assertEqual(evidence["calibration_split"], "validation")
            self.assertEqual(evidence["evaluation_split"], "test")
            self.assertEqual(evidence["models"]["adapted"]["report"]["model_size_bytes"], 20)
            output = Path(directory) / "evidence.json"
            write_evidence(output, evidence)
            self.assertEqual(json.loads(output.read_text())["manifest_digest"], manifest.digest())

    def test_csv_must_match_manifest_exactly(self) -> None:
        rows = (self._row("train", "train", 0, "a"),)
        manifest = DatasetManifest(Path("."), rows)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "scores.csv"
            path.write_text("sample_id,score\ntrain,0.1\nextra,0.2\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "exactly match"):
                compare_score_csvs(manifest, path, path)
