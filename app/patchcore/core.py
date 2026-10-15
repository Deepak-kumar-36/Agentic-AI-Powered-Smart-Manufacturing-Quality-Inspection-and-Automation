"""Dependency-lazy PatchCore numerical core and optional torchvision backbone."""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Callable, Mapping, Sequence

import numpy as np


class PatchCoreDependencyError(RuntimeError):
    pass


@dataclass(frozen=True)
class PatchCoreConfig:
    memory_bank_size: int = 10_000
    coreset_seed: int = 0
    neighbors: int = 1
    heatmap_sigma: float = 0.0
    distance_chunk_size: int = 4096

    def __post_init__(self) -> None:
        if (
            self.memory_bank_size < 1
            or self.neighbors < 1
            or self.heatmap_sigma < 0
            or self.distance_chunk_size < 1
        ):
            raise ValueError("memory_bank_size, neighbors, and distance_chunk_size must be positive; sigma non-negative")


@dataclass(frozen=True)
class PatchCoreResult:
    score: float
    heatmap: np.ndarray
    nearest_distances: np.ndarray


def _finite_array(values: Any, *, name: str, ndim: int | None = None) -> np.ndarray:
    array = np.asarray(values, dtype=np.float32)
    if ndim is not None and array.ndim != ndim:
        raise ValueError(f"{name} must have {ndim} dimensions, got {array.ndim}")
    if array.size == 0 or not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must be non-empty and finite")
    return array


def align_feature_maps(features: Mapping[str, Any]) -> np.ndarray:
    """Align CHW feature maps to the largest spatial resolution and concatenate."""
    if not features:
        raise ValueError("at least one feature map is required")
    arrays = [_finite_array(value, name=f"feature[{key}]", ndim=4) for key, value in features.items()]
    if any(value.shape[0] != arrays[0].shape[0] for value in arrays):
        raise ValueError("feature maps must have the same batch size")
    target_h = max(value.shape[-2] for value in arrays)
    target_w = max(value.shape[-1] for value in arrays)
    if any(value.shape[-2:] != (target_h, target_w) for value in arrays):
        try:
            import torch
            import torch.nn.functional as F
            tensors = [torch.as_tensor(value) for value in arrays]
            arrays = [F.interpolate(value, size=(target_h, target_w), mode="bilinear", align_corners=False).numpy() for value in tensors]
        except ImportError as exc:
            raise PatchCoreDependencyError("torch is required to align feature maps of different sizes") from exc
    return np.concatenate(arrays, axis=1)


def patch_embeddings(feature_maps: Any) -> np.ndarray:
    """Convert BCHW maps to (B*H*W, C) patch vectors."""
    array = _finite_array(feature_maps, name="feature_maps", ndim=4)
    return np.moveaxis(array, 1, -1).reshape(-1, array.shape[1])


def deterministic_coreset(embeddings: Any, limit: int, seed: int = 0) -> np.ndarray:
    """Deterministic farthest-point coreset, bounded by ``limit``."""
    points = _finite_array(embeddings, name="embeddings", ndim=2)
    if limit < 1:
        raise ValueError("limit must be positive")
    if len(points) <= limit:
        return points.copy()
    rng = np.random.default_rng(seed)
    selected = [int(rng.integers(len(points)))]
    distances = np.sum((points - points[selected[0]]) ** 2, axis=1)
    for _ in range(1, limit):
        index = int(np.argmax(distances))
        selected.append(index)
        distances = np.minimum(distances, np.sum((points - points[index]) ** 2, axis=1))
    return points[np.asarray(selected)]


def build_memory_bank(embeddings: Any, config: PatchCoreConfig | None = None) -> np.ndarray:
    """Build a bounded deterministic memory bank from patch embeddings."""
    settings = config or PatchCoreConfig()
    return deterministic_coreset(embeddings, settings.memory_bank_size, settings.coreset_seed)


def nearest_neighbor_distances(
    queries: Any,
    bank: Any,
    neighbors: int = 1,
    chunk_size: int = 4096,
) -> np.ndarray:
    query = _finite_array(queries, name="queries", ndim=2)
    memory = _finite_array(bank, name="memory_bank", ndim=2)
    if query.shape[1] != memory.shape[1] or neighbors < 1 or chunk_size < 1:
        raise ValueError("embedding dimensions must match; neighbors and chunk_size must be positive")
    k = min(neighbors, len(memory))
    result = np.empty(len(query), dtype=np.float32)
    for start in range(0, len(query), chunk_size):
        batch = query[start : start + chunk_size]
        distances = np.sqrt(
            np.maximum(0, ((batch[:, None, :] - memory[None, :, :]) ** 2).sum(axis=2))
        )
        nearest = np.partition(distances, k - 1, axis=1)[:, :k]
        result[start : start + len(batch)] = nearest.mean(axis=1)
    return result


def reconstruct_heatmap(distances: Any, shape: tuple[int, int], sigma: float = 0.0) -> np.ndarray:
    values = _finite_array(distances, name="distances", ndim=2)
    height, width = shape
    if height < 1 or width < 1 or values.shape[0] != height * width:
        raise ValueError("distance count must equal heatmap height*width")
    heatmap = values.mean(axis=1).reshape(height, width)
    if sigma:
        try:
            from scipy.ndimage import gaussian_filter  # type: ignore[import-not-found]
            heatmap = gaussian_filter(heatmap, sigma=sigma)
        except ImportError:
            # A dependency-free 3x3 approximation preserves importability.
            padded = np.pad(heatmap, 1, mode="edge")
            heatmap = sum(padded[i : i + height, j : j + width] for i in range(3) for j in range(3)) / 9
    return heatmap.astype(np.float32)


def build_wide_resnet50_extractor(*, weights: Any = None) -> Callable[[Any], Mapping[str, Any]]:
    """Create an eval/no-grad WideResNet50-2 layer2/layer3 extractor lazily."""
    try:
        import torch
        from torchvision.models import wide_resnet50_2
    except ImportError as exc:
        raise PatchCoreDependencyError("torch and torchvision are required for WideResNet50-2") from exc
    if weights is None:
        raise PatchCoreDependencyError(
            "pass an explicit torchvision weights object; weight acquisition must be an intentional setup step"
        )
    model = wide_resnet50_2(weights=weights)
    model.eval()

    def extract(batch: Any) -> Mapping[str, Any]:
        if not isinstance(batch, torch.Tensor) or batch.ndim != 4 or batch.shape[1] != 3:
            raise ValueError("backbone input must be a 4D torch tensor with three channels")
        if not batch.is_floating_point() or not bool(torch.isfinite(batch).all()):
            raise ValueError("backbone input must be finite floating-point data")
        outputs: dict[str, Any] = {}
        def hook(name: str):
            return lambda _module, _args, output: outputs.__setitem__(name, output)
        handles = [model.layer2.register_forward_hook(hook("layer2")), model.layer3.register_forward_hook(hook("layer3"))]
        try:
            with torch.no_grad():
                model(batch)
        finally:
            for handle in handles:
                handle.remove()
        return outputs
    return extract


class PatchCorePipeline:
    def __init__(self, config: PatchCoreConfig | None = None) -> None:
        self.config = config or PatchCoreConfig()
        self.memory_bank: np.ndarray | None = None

    def fit(self, embeddings: Any) -> np.ndarray:
        self.memory_bank = build_memory_bank(embeddings, self.config)
        return self.memory_bank.copy()

    def score(self, embeddings: Any, grid_shape: tuple[int, int]) -> PatchCoreResult:
        if self.memory_bank is None:
            raise RuntimeError("fit must be called before score")
        distances = nearest_neighbor_distances(
            embeddings,
            self.memory_bank,
            self.config.neighbors,
            self.config.distance_chunk_size,
        )
        heatmap = reconstruct_heatmap(distances[:, None], grid_shape, self.config.heatmap_sigma)
        return PatchCoreResult(float(np.max(distances)), heatmap, distances)
