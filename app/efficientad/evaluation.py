"""Calibration and locked-split evaluation for EfficientAD-S experiments.

The helpers in this module deliberately keep calibration and final evaluation
separate: thresholds are fitted from validation rows, while test rows are
only scored with the resulting policy.  CSV files contain scores only; labels
and split membership come from the immutable dataset manifest.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import csv
import json
import math
from pathlib import Path
from typing import Mapping, Sequence


@dataclass(frozen=True)
class CostConfig:
    """Business costs used when selecting a validation threshold."""

    false_accept_cost: float = 1.0
    false_reject_cost: float = 1.0

    def __post_init__(self) -> None:
        if self.false_accept_cost < 0 or self.false_reject_cost < 0:
            raise ValueError("false-accept and false-reject costs cannot be negative")
        if self.false_accept_cost == 0 and self.false_reject_cost == 0:
            raise ValueError("at least one error cost must be positive")


@dataclass(frozen=True)
class ReviewBand:
    """Optional inclusive score interval routed to human review.

    Scores below ``lower`` are normal, scores from ``lower`` through ``upper``
    are review, and scores above ``upper`` are anomalous.  The interval is
    explicit so callers cannot accidentally treat reviewed samples as rejects.
    """

    lower: float
    upper: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.lower) or not math.isfinite(self.upper) or self.lower > self.upper:
            raise ValueError("review band bounds must be finite and ordered")


@dataclass(frozen=True)
class ThresholdPolicy:
    threshold: float
    costs: CostConfig
    review_band: ReviewBand | None = None
    selection_split: str = "validation"

    def __post_init__(self) -> None:
        if not math.isfinite(self.threshold):
            raise ValueError("threshold must be finite")

    def classify(self, score: float) -> str:
        if not math.isfinite(score):
            raise ValueError("score must be finite")
        if self.review_band and self.review_band.lower <= score <= self.review_band.upper:
            return "review"
        return "anomaly" if score >= self.threshold else "normal"

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ScoreRow:
    sample_id: str
    score: float
    latency_ms: float | None = None
    model_size_bytes: int | None = None


def _validate(scores: Sequence[float], labels: Sequence[int]) -> None:
    if len(scores) != len(labels) or not scores:
        raise ValueError("scores and labels must be equally sized and non-empty")
    if any(not math.isfinite(float(value)) for value in scores):
        raise ValueError("scores must be finite")
    if any(label not in (0, 1) for label in labels):
        raise ValueError("labels must be 0 or 1")


def select_threshold(
    scores: Sequence[float],
    labels: Sequence[int],
    *,
    costs: CostConfig | None = None,
    false_accept_cost: float | None = None,
    false_reject_cost: float | None = None,
) -> float:
    """Select a threshold from validation data only.

    With no costs this preserves the historical maximum-F1 behavior.  With
    costs, the threshold minimizes ``FA * false_accept_cost + FR * false_reject_cost``.
    """
    _validate(scores, labels)
    if costs is not None and (false_accept_cost is not None or false_reject_cost is not None):
        raise ValueError("provide costs or individual cost arguments, not both")
    use_f1 = costs is None and false_accept_cost is None and false_reject_cost is None
    costs = costs or CostConfig(
        1.0 if false_accept_cost is None else false_accept_cost,
        1.0 if false_reject_cost is None else false_reject_cost,
    )
    candidates = sorted(set(float(value) for value in scores))
    candidates.insert(0, math.nextafter(candidates[0], -math.inf))
    best_key: tuple[float, float] | None = None
    for threshold in candidates:
        predicted = [score >= threshold for score in scores]
        tp = sum(p and label == 1 for p, label in zip(predicted, labels))
        fp = sum(p and label == 0 for p, label in zip(predicted, labels))
        fn = sum(not p and label == 1 for p, label in zip(predicted, labels))
        if use_f1:
            value = -(0.0 if 2 * tp + fp + fn == 0 else (2 * tp) / (2 * tp + fp + fn))
        else:
            value = fp * costs.false_accept_cost + fn * costs.false_reject_cost
        key = (value, threshold)
        if best_key is None or key < best_key:
            best_key = key
    assert best_key is not None
    return best_key[1]


def calibrate_threshold(scores: Sequence[float], labels: Sequence[int], costs: CostConfig | None = None, review_band: ReviewBand | None = None) -> ThresholdPolicy:
    """Fit a policy using validation rows; never accepts a test split argument."""
    return ThresholdPolicy(select_threshold(scores, labels, costs=costs), costs or CostConfig(), review_band)


def _auroc(scores: Sequence[float], labels: Sequence[int]) -> float | None:
    positives = sum(label == 1 for label in labels)
    negatives = sum(label == 0 for label in labels)
    if positives == 0 or negatives == 0:
        return None
    order = sorted(scores)
    rank_sum = 0.0
    index = 0
    while index < len(order):
        end = index + 1
        while end < len(order) and order[end] == order[index]:
            end += 1
        average_rank = (index + 1 + end) / 2
        rank_sum += sum(label == 1 for score, label in zip(scores, labels) if score == order[index]) * average_rank
        index = end
    return (rank_sum - positives * (positives + 1) / 2) / (positives * negatives)


@dataclass(frozen=True)
class EvaluationReport:
    split: str
    sample_count: int
    threshold: float
    auroc: float | None
    precision: float
    recall: float
    f1: float
    true_positive: int
    false_positive: int
    true_negative: int
    false_negative: int
    false_rejection_normal: float
    missed_defect_rate: float
    review_count: int = 0
    latency_ms_mean: float | None = None
    latency_ms_p95: float | None = None
    model_size_bytes: int | None = None

    @property
    def confusion_matrix(self) -> dict[str, int]:
        return {"true_positive": self.true_positive, "false_positive": self.false_positive,
                "true_negative": self.true_negative, "false_negative": self.false_negative}

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["confusion_matrix"] = self.confusion_matrix
        return payload


def evaluate_scores(scores: Sequence[float], labels: Sequence[int], threshold: float, split: str, *, policy: ThresholdPolicy | None = None, latency_ms: Sequence[float] | None = None, model_size_bytes: int | None = None) -> EvaluationReport:
    _validate(scores, labels)
    if not math.isfinite(threshold):
        raise ValueError("threshold must be finite")
    if latency_ms is not None and (len(latency_ms) != len(scores) or any(value < 0 or not math.isfinite(value) for value in latency_ms)):
        raise ValueError("latency_ms must match scores and contain finite non-negative values")
    if model_size_bytes is not None and model_size_bytes < 0:
        raise ValueError("model_size_bytes cannot be negative")
    classify = policy.classify if policy else lambda score: "anomaly" if score >= threshold else "normal"
    decisions = [classify(float(score)) for score in scores]
    predicted = [decision == "anomaly" for decision in decisions]
    tp = sum(p and label == 1 for p, label in zip(predicted, labels))
    fp = sum(p and label == 0 for p, label in zip(predicted, labels))
    tn = sum(not p and label == 0 for p, label in zip(predicted, labels))
    fn = sum(not p and label == 1 for p, label in zip(predicted, labels))
    precision = 0.0 if tp + fp == 0 else tp / (tp + fp)
    recall = 0.0 if tp + fn == 0 else tp / (tp + fn)
    normal_count = tn + fp
    defect_count = tp + fn
    return EvaluationReport(split, len(scores), threshold, _auroc(scores, labels), precision, recall,
                            0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall),
                            tp, fp, tn, fn, fp / normal_count if normal_count else 0.0,
                            fn / defect_count if defect_count else 0.0, decisions.count("review"),
                            sum(latency_ms) / len(latency_ms) if latency_ms else None,
                            sorted(latency_ms)[math.ceil(len(latency_ms) * .95) - 1] if latency_ms else None,
                            model_size_bytes)


def read_score_csv(path: str | Path) -> tuple[ScoreRow, ...]:
    """Read score rows; manifest remains the source of labels and split locks."""
    with Path(path).open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or not {"sample_id", "score"} <= set(reader.fieldnames):
            raise ValueError("score CSV requires sample_id and score columns")
        rows = []
        for record in reader:
            try:
                rows.append(ScoreRow(record["sample_id"], float(record["score"]),
                                     float(record["latency_ms"]) if record.get("latency_ms") else None,
                                     int(record["model_size_bytes"]) if record.get("model_size_bytes") else None))
            except (TypeError, ValueError) as exc:
                raise ValueError("score CSV contains an invalid row") from exc
    if not rows or len({row.sample_id for row in rows}) != len(rows):
        raise ValueError("score CSV must contain unique, non-empty rows")
    return tuple(rows)


def compare_score_csvs(manifest, baseline_csv: str | Path, adapted_csv: str | Path, *, costs: CostConfig | None = None, review_band: ReviewBand | None = None) -> dict[str, object]:
    """Calibrate independently on validation and compare both models on test."""
    by_id = {row.sample_id: row for row in manifest.rows}
    output: dict[str, object] = {"manifest_digest": manifest.digest(), "calibration_split": "validation", "evaluation_split": "test", "models": {}}
    for name, path in (("baseline", baseline_csv), ("adapted", adapted_csv)):
        rows = read_score_csv(path)
        score_ids = {row.sample_id for row in rows}
        required_ids = {sample_id for sample_id, manifest_row in by_id.items() if manifest_row.split in {"validation", "test"}}
        if not required_ids <= score_ids or not score_ids <= set(by_id):
            raise ValueError(f"{name} scores do not exactly match manifest validation/test rows")
        validation = [row for row in rows if by_id[row.sample_id].split == "validation"]
        test = [row for row in rows if by_id[row.sample_id].split == "test"]
        policy = calibrate_threshold([row.score for row in validation], [by_id[row.sample_id].label for row in validation], costs, review_band)
        report = evaluate_scores([row.score for row in test], [by_id[row.sample_id].label for row in test], policy.threshold, "test", policy=policy,
                                 latency_ms=[row.latency_ms for row in test] if all(row.latency_ms is not None for row in test) else None,
                                 model_size_bytes=next((row.model_size_bytes for row in rows if row.model_size_bytes is not None), None))
        output["models"][name] = {"policy": policy.as_dict(), "validation_count": len(validation), "report": report.as_dict()}
    return output


def write_evidence(path: str | Path, evidence: Mapping[str, object]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
