"""Evidence-producing diagnostics for EfficientAD-S domain-shift investigations."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any

import numpy as np

from .native import image_transform, infer_loaded, overlay_image


@dataclass(frozen=True)
class DiagnosticReport:
    image_path: str
    model_version: str
    preprocessing: dict[str, Any]
    original_size: tuple[int, int]
    preprocessed_shape: tuple[int, ...]
    preprocessed_min: float
    preprocessed_max: float
    preprocessed_mean: float
    score: float
    heatmap_path: str
    overlay_path: str | None
    thresholds: dict[str, float | None]
    outcome: str
    reason_codes: list[str]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def diagnose_image(
    bundle: Any,
    image_path: str | Path,
    output_dir: str | Path,
    *,
    model_version: str,
    pass_threshold: float | None = None,
    fail_threshold: float | None = None,
    category: str = "capsule",
) -> DiagnosticReport:
    """Save heatmap/overlay evidence and report the exact serving transform.

    This function does not label a sample from thresholds unless both thresholds
    are supplied. It is safe to use before real-capsule data is available.
    """
    from PIL import Image

    source = Path(image_path)
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as opened:
        original = opened.convert("RGB")
        original_size = original.size
        tensor = image_transform()(original)
    score, anomaly_map = infer_loaded(bundle, source)
    stem = source.stem
    heatmap_path = destination / f"{stem}.heatmap.png"
    overlay_path = destination / f"{stem}.overlay.png"
    normalized = anomaly_map - float(np.min(anomaly_map))
    maximum = float(np.max(normalized))
    if maximum > 0:
        normalized = normalized / maximum
    Image.fromarray(np.uint8(np.clip(normalized, 0, 1) * 255), mode="L").save(heatmap_path)
    overlay_image(source, normalized, overlay_path)

    outcome = "UNVERIFIED"
    reasons = ["THRESHOLDS_NOT_PROVIDED"]
    if pass_threshold is not None and fail_threshold is not None:
        if pass_threshold >= fail_threshold:
            raise ValueError("pass threshold must be less than fail threshold")
        if score <= pass_threshold:
            outcome, reasons = "PASS", ["ACCEPTED_BY_POLICY"]
        elif score >= fail_threshold:
            outcome, reasons = "FAIL", ["REJECTED_BY_POLICY"]
        else:
            outcome, reasons = "UNVERIFIED", ["REVIEW_BAND"]
    report = DiagnosticReport(
        image_path=str(source), model_version=model_version,
        preprocessing={"resize": [256, 256], "color": "RGB", "to_tensor": True,
                       "normalize_mean": [0.485, 0.456, 0.406],
                       "normalize_std": [0.229, 0.224, 0.225], "category": category},
        original_size=original_size, preprocessed_shape=tuple(int(value) for value in tensor.shape),
        preprocessed_min=float(tensor.min()), preprocessed_max=float(tensor.max()),
        preprocessed_mean=float(tensor.mean()), score=score,
        heatmap_path=str(heatmap_path), overlay_path=str(overlay_path),
        thresholds={"pass": pass_threshold, "fail": fail_threshold}, outcome=outcome,
        reason_codes=reasons,
    )
    (destination / f"{stem}.diagnostic.json").write_text(json.dumps(report.as_dict(), indent=2) + "\n", encoding="utf-8")
    return report
