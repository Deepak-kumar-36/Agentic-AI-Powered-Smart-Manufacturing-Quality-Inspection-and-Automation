"""Load reviewed Kaggle EfficientAD artifacts without silently qualifying them."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Mapping

from .native import sha256_file
from .runtime import NativeEfficientADRuntime
from ..api import InspectionApi
from ..policy import DecisionPolicy


class EfficientADReleaseError(RuntimeError):
    """Raised when Kaggle output is incomplete or not approved for local use."""


@dataclass(frozen=True)
class ReviewedEfficientADRelease:
    metadata_path: Path
    artifact_root: Path
    teacher_path: Path
    checkpoints: dict[str, Path]
    policies: dict[str, DecisionPolicy]
    metadata: dict[str, object]

    def create_api(self, *, device: str = "cpu", image_root: str | Path | None = None, store=None) -> InspectionApi:
        runtime = NativeEfficientADRuntime(self.checkpoints, self.teacher_path, device=device)
        return InspectionApi(store, model=runtime, policies=self.policies, image_root=image_root)


def load_reviewed_release(
    metadata_path: str | Path,
    artifact_root: str | Path,
    teacher_path: str | Path,
    policy_thresholds: Mapping[str, tuple[float, float]],
) -> ReviewedEfficientADRelease:
    """Validate reviewed metadata and return an API-ready release description.

    Policy thresholds are deliberately supplied by the reviewer rather than
    inferred from Kaggle metrics. The loader refuses smoke runs and metadata
    that has not been explicitly marked ``QUALIFIED``.
    """
    metadata_file = Path(metadata_path)
    root = Path(artifact_root)
    teacher = Path(teacher_path)
    try:
        metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EfficientADReleaseError(f"unable to read release metadata: {metadata_file}") from exc
    if not isinstance(metadata, dict):
        raise EfficientADReleaseError("release metadata must be a JSON object")
    if metadata.get("run_mode") != "full":
        raise EfficientADReleaseError("only full Kaggle runs can be loaded")
    if metadata.get("qualification_status") not in {"QUALIFIED", "QUALIFIED_FOR_SUPERVISED_LOCAL_API"}:
        raise EfficientADReleaseError("release metadata is not explicitly qualified")
    if metadata.get("implementation") != "native":
        raise EfficientADReleaseError("release is not the native EfficientAD implementation")
    categories = metadata.get("categories")
    if not isinstance(categories, list) or not categories or any(not isinstance(item, str) for item in categories):
        raise EfficientADReleaseError("release categories are missing or invalid")
    if not teacher.is_file():
        raise EfficientADReleaseError(f"teacher checkpoint not found: {teacher}")
    if metadata.get("teacher_sha256") != sha256_file(teacher):
        raise EfficientADReleaseError("reference teacher hash does not match release metadata")
    if set(categories) != set(policy_thresholds):
        raise EfficientADReleaseError("policy thresholds must cover exactly the release categories")

    summary = metadata.get("training_summary")
    if not isinstance(summary, list):
        raise EfficientADReleaseError("training_summary is missing")
    by_category = {item.get("category"): item for item in summary if isinstance(item, dict)}
    checkpoints: dict[str, Path] = {}
    policies: dict[str, DecisionPolicy] = {}
    for category in categories:
        checkpoint = root / "reference_teacher" / category / f"efficientad_s_{category}.pt"
        if not checkpoint.is_file():
            raise EfficientADReleaseError(f"checkpoint not found for {category}: {checkpoint}")
        expected_hash = by_category.get(category, {}).get("checkpoint_sha256")
        if expected_hash != sha256_file(checkpoint):
            raise EfficientADReleaseError(f"checkpoint hash does not match release metadata for {category}")
        pass_threshold, fail_threshold = policy_thresholds[category]
        policies[category] = DecisionPolicy(
            version=f"efficientad-s-native-v1:{category}",
            compatible_model_versions=frozenset({NativeEfficientADRuntime.MODEL_VERSION}),
            pass_threshold=pass_threshold,
            fail_threshold=fail_threshold,
        )
        checkpoints[category] = checkpoint
    return ReviewedEfficientADRelease(metadata_file, root, teacher, checkpoints, policies, metadata)
