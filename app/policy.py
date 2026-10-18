"""Deterministic, fail-closed inspection decision policy.

This module deliberately has no model, camera, database, or hardware dependency.
It consumes validated evidence and produces an auditable terminal outcome.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from typing import Iterable


class Outcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNVERIFIED = "UNVERIFIED"


class ReasonCode(str, Enum):
    ACCEPTED_BY_POLICY = "ACCEPTED_BY_POLICY"
    REJECTED_BY_POLICY = "REJECTED_BY_POLICY"
    IMAGE_INVALID = "IMAGE_INVALID"
    FRAME_STALE = "FRAME_STALE"
    MODEL_NOT_READY = "MODEL_NOT_READY"
    MODEL_OUTPUT_INVALID = "MODEL_OUTPUT_INVALID"
    MODEL_VERSION_INCOMPATIBLE = "MODEL_VERSION_INCOMPATIBLE"
    MODEL_SCORE_IN_REVIEW_BAND = "MODEL_SCORE_IN_REVIEW_BAND"
    UNSUPPORTED_CATEGORY = "UNSUPPORTED_CATEGORY"


@dataclass(frozen=True)
class ModelEvidence:
    """Normalized model output; score is not assumed to be a probability."""

    model_version: str | None
    score: float | None
    score_type: str = "anomaly_score"
    available: bool = True


@dataclass(frozen=True)
class InspectionInput:
    """Input-quality facts known before policy evaluation."""

    valid: bool = True
    stale: bool = False


@dataclass(frozen=True)
class Decision:
    outcome: Outcome
    reason_codes: tuple[ReasonCode, ...]
    policy_version: str
    model_version: str | None
    score: float | None


@dataclass(frozen=True)
class DecisionPolicy:
    """Three-band anomaly policy for scores where higher means more anomalous."""

    version: str
    compatible_model_versions: frozenset[str]
    pass_threshold: float
    fail_threshold: float

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise ValueError("policy version must not be empty")
        if not math.isfinite(self.pass_threshold) or not math.isfinite(self.fail_threshold):
            raise ValueError("policy thresholds must be finite")
        if self.pass_threshold >= self.fail_threshold:
            raise ValueError("pass_threshold must be less than fail_threshold")
        if not self.compatible_model_versions:
            raise ValueError("at least one compatible model version is required")

    def evaluate(self, image: InspectionInput, evidence: ModelEvidence) -> Decision:
        """Return a terminal outcome without defaulting missing evidence to PASS."""

        base = {
            "policy_version": self.version,
            "model_version": evidence.model_version,
            "score": evidence.score,
        }
        if not image.valid:
            return Decision(Outcome.UNVERIFIED, (ReasonCode.IMAGE_INVALID,), **base)
        if image.stale:
            return Decision(Outcome.UNVERIFIED, (ReasonCode.FRAME_STALE,), **base)
        if not evidence.available:
            return Decision(Outcome.UNVERIFIED, (ReasonCode.MODEL_NOT_READY,), **base)
        if evidence.model_version not in self.compatible_model_versions:
            return Decision(
                Outcome.UNVERIFIED,
                (ReasonCode.MODEL_VERSION_INCOMPATIBLE,),
                **base,
            )
        if evidence.score is None or not math.isfinite(evidence.score):
            return Decision(Outcome.UNVERIFIED, (ReasonCode.MODEL_OUTPUT_INVALID,), **base)
        if evidence.score <= self.pass_threshold:
            return Decision(Outcome.PASS, (ReasonCode.ACCEPTED_BY_POLICY,), **base)
        if evidence.score >= self.fail_threshold:
            return Decision(Outcome.FAIL, (ReasonCode.REJECTED_BY_POLICY,), **base)
        return Decision(Outcome.UNVERIFIED, (ReasonCode.MODEL_SCORE_IN_REVIEW_BAND,), **base)


def reason_values(codes: Iterable[ReasonCode]) -> list[str]:
    """Serialize reason codes without exposing implementation details."""

    return [code.value for code in codes]
