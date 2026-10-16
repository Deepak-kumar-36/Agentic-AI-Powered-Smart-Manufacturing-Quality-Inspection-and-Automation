from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Iterable, Sequence


def select_threshold(scores: Sequence[float], labels: Sequence[int]) -> float:
    """Select the threshold maximizing F1 on validation data only."""
    if len(scores) != len(labels) or not scores:
        raise ValueError("scores and labels must be equally sized and non-empty")
    if any(not math.isfinite(value) for value in scores):
        raise ValueError("scores must be finite")
    candidates = sorted(set(float(value) for value in scores))
    best = (-1.0, candidates[0])
    for threshold in candidates:
        predicted = [score >= threshold for score in scores]
        tp = sum(p and label == 1 for p, label in zip(predicted, labels))
        fp = sum(p and label == 0 for p, label in zip(predicted, labels))
        fn = sum(not p and label == 1 for p, label in zip(predicted, labels))
        f1 = 0.0 if 2 * tp + fp + fn == 0 else (2 * tp) / (2 * tp + fp + fn)
        if f1 > best[0]:
            best = (f1, threshold)
    return best[1]


def _auroc(scores: Sequence[float], labels: Sequence[int]) -> float | None:
    positives = sum(label == 1 for label in labels)
    negatives = sum(label == 0 for label in labels)
    if positives == 0 or negatives == 0:
        return None
    order = sorted(range(len(scores)), key=lambda index: scores[index])
    rank_sum = sum(rank for rank, index in enumerate(order, 1) if labels[index] == 1)
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

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def evaluate_scores(scores: Sequence[float], labels: Sequence[int], threshold: float, split: str) -> EvaluationReport:
    if len(scores) != len(labels) or not scores:
        raise ValueError("scores and labels must be equally sized and non-empty")
    if any(not math.isfinite(value) for value in scores):
        raise ValueError("scores must be finite")
    predicted = [score >= threshold for score in scores]
    tp = sum(p and label == 1 for p, label in zip(predicted, labels))
    fp = sum(p and label == 0 for p, label in zip(predicted, labels))
    fn = sum(not p and label == 1 for p, label in zip(predicted, labels))
    precision = 0.0 if tp + fp == 0 else tp / (tp + fp)
    recall = 0.0 if tp + fn == 0 else tp / (tp + fn)
    f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
    return EvaluationReport(split, len(scores), threshold, _auroc(scores, labels), precision, recall, f1)
