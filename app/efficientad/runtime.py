"""Dependency-lazy runtime adapter for verified native EfficientAD-S releases."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .native import EfficientADDependencyError, infer_loaded, load_model_bundle, load_teacher, sha256_file


class EfficientADRuntimeError(RuntimeError):
    """Raised when an EfficientAD release cannot be used safely."""


@dataclass(frozen=True)
class EfficientADImageScore:
    category: str
    image: Path
    score: float
    heatmap: Any
    model_version: str
    checkpoint: Path


class NativeEfficientADRuntime:
    """Score images with explicitly mapped, hash-verified category checkpoints.

    The adapter deliberately keeps model availability separate from the API and
    never downloads weights. Each category must have its own checkpoint and the
    checkpoint must identify the expected native variant and teacher hash.
    """

    MODEL_VERSION = "efficientad-s-native-v1"
    VARIANT = "EfficientAD-S-ReferenceTeacher-MVTecOnly"

    def __init__(
        self,
        checkpoints: dict[str, str | Path],
        teacher_path: str | Path,
        *,
        device: str = "cpu",
    ) -> None:
        if not checkpoints:
            raise ValueError("at least one category checkpoint is required")
        if any(not category.strip() for category in checkpoints):
            raise ValueError("checkpoint categories must not be empty")
        self.checkpoints = {category: Path(path) for category, path in checkpoints.items()}
        self.teacher_path = Path(teacher_path)
        self.device = device
        self._bundles: dict[str, Any] = {}
        self._validate_paths()
        self._validate_teacher_dependency()

    def _validate_paths(self) -> None:
        if not self.teacher_path.is_file():
            raise EfficientADRuntimeError(f"teacher checkpoint not found: {self.teacher_path}")
        missing = [str(path) for path in self.checkpoints.values() if not path.is_file()]
        if missing:
            raise EfficientADRuntimeError(f"category checkpoint(s) not found: {', '.join(missing)}")

    def _validate_teacher_dependency(self) -> None:
        try:
            import torch
        except ImportError as exc:
            raise EfficientADDependencyError("native EfficientAD requires torch, torchvision, and Pillow") from exc
        try:
            teacher = load_teacher(self.teacher_path, torch.device(self.device))
            del teacher
        except Exception as exc:
            raise EfficientADRuntimeError(f"unable to load teacher checkpoint: {self.teacher_path}") from exc

    def _checkpoint_payload(self, category: str) -> dict[str, Any]:
        try:
            import torch
        except ImportError as exc:
            raise EfficientADDependencyError("native EfficientAD requires torch, torchvision, and Pillow") from exc
        path = self.checkpoints[category]
        try:
            payload = torch.load(path, map_location="cpu", weights_only=True)
        except Exception as exc:
            raise EfficientADRuntimeError(f"unable to load category checkpoint: {path}") from exc
        if not isinstance(payload, dict):
            raise EfficientADRuntimeError(f"checkpoint payload is not a mapping: {path}")
        if payload.get("category") != category:
            raise EfficientADRuntimeError(f"checkpoint category mismatch for {category}: {path}")
        if payload.get("variant") != self.VARIANT:
            raise EfficientADRuntimeError(f"unsupported EfficientAD variant: {path}")
        expected_teacher = payload.get("teacher_sha256")
        actual_teacher = sha256_file(self.teacher_path)
        if expected_teacher != actual_teacher:
            raise EfficientADRuntimeError(f"teacher hash mismatch for {category}: {path}")
        for key in ("student", "autoencoder", "teacher_mean", "teacher_std"):
            if key not in payload:
                raise EfficientADRuntimeError(f"checkpoint missing {key}: {path}")
        return payload

    def score(self, category: str, image: str | Path) -> EfficientADImageScore:
        if category not in self.checkpoints:
            raise EfficientADRuntimeError(f"category is not configured: {category}")
        payload = self._checkpoint_payload(category)
        del payload
        checkpoint = self.checkpoints[category]
        if category not in self._bundles:
            self._bundles[category] = load_model_bundle(checkpoint, self.teacher_path, self.device)
        score, heatmap = infer_loaded(self._bundles[category], image)
        return EfficientADImageScore(category, Path(image), score, heatmap, self.MODEL_VERSION, checkpoint)
