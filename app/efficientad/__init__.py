"""Reusable, dependency-lazy EfficientAD-S experiment utilities."""

from .config import EfficientADConfig
from .data import (
    CapsuleDiscoveryConfig,
    DatasetManifest,
    ManifestIssue,
    ManifestRow,
    discover_dataset_manifest,
    discover_mvtec_manifest,
    discover_real_capsule_manifest,
    validate_manifest,
)
from .evaluation import (
    CostConfig,
    EvaluationReport,
    ReviewBand,
    ScoreRow,
    ThresholdPolicy,
    calibrate_threshold,
    compare_score_csvs,
    evaluate_scores,
    read_score_csv,
    select_threshold,
    write_evidence,
)
from .runtime import EfficientADImageScore, EfficientADRuntimeError, NativeEfficientADRuntime
from .diagnostics import DiagnosticReport, diagnose_image

__all__ = [
    "DatasetManifest",
    "CapsuleDiscoveryConfig",
    "EfficientADConfig",
    "EvaluationReport",
    "CostConfig",
    "ReviewBand",
    "ScoreRow",
    "ThresholdPolicy",
    "EfficientADImageScore",
    "EfficientADRuntimeError",
    "ManifestRow",
    "ManifestIssue",
    "NativeEfficientADRuntime",
    "calibrate_threshold",
    "compare_score_csvs",
    "discover_dataset_manifest",
    "discover_mvtec_manifest",
    "discover_real_capsule_manifest",
    "evaluate_scores",
    "read_score_csv",
    "select_threshold",
    "write_evidence",
    "validate_manifest",
    "DiagnosticReport",
    "diagnose_image",
]
