"""Image-to-PatchCore runtime using an explicitly selected pretrained backbone."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np

from .core import PatchCoreConfig, PatchCoreDependencyError, PatchCorePipeline, align_feature_maps, patch_embeddings
from .dataset import MVTecFile


@dataclass(frozen=True)
class ImageScore:
    image: Path
    score: float
    heatmap: np.ndarray
    grid_shape: tuple[int, int]


class WideResNetPatchCore:
    """CPU/GPU inference wrapper with no implicit weight download in the API."""

    def __init__(self, config: PatchCoreConfig | None = None, *, weights: str = "DEFAULT", device: str = "cpu", batch_size: int = 8) -> None:
        try:
            import torch
            from torchvision.models import Wide_ResNet50_2_Weights
        except ImportError as exc:
            raise PatchCoreDependencyError("torch and torchvision are required for image inference") from exc
        if weights != "DEFAULT":
            raise ValueError("only the explicit torchvision DEFAULT weight enum is supported")
        self.torch = torch
        self.device = torch.device(device)
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        self.batch_size = batch_size
        self.weight_enum = Wide_ResNet50_2_Weights.DEFAULT
        self.extractor = self._build_extractor()
        self.transform = self.weight_enum.transforms()
        self.pipeline = PatchCorePipeline(config)

    def _build_extractor(self):
        from torchvision.models import wide_resnet50_2

        model = wide_resnet50_2(weights=self.weight_enum).to(self.device)
        model.eval()

        def extract(batch):
            outputs = {}

            def hook(name):
                return lambda _module, _args, output: outputs.__setitem__(name, output.detach().cpu().numpy())

            handles = [model.layer2.register_forward_hook(hook("layer2")), model.layer3.register_forward_hook(hook("layer3"))]
            try:
                with self.torch.no_grad():
                    model(batch.to(self.device))
            finally:
                for handle in handles:
                    handle.remove()
            return outputs

        return extract

    def _embeddings(self, paths: Iterable[Path]) -> tuple[np.ndarray, tuple[int, int]]:
        from PIL import Image

        paths = list(paths)
        images = []
        for path in paths:
            with Image.open(path) as image:
                images.append(self.transform(image.convert("RGB")))
        if not images:
            raise ValueError("at least one image is required")
        all_embeddings = []
        grid_shape = None
        for start in range(0, len(images), self.batch_size):
            features = align_feature_maps(self.extractor(self.torch.stack(images[start : start + self.batch_size])))
            current_shape = (int(features.shape[-2]), int(features.shape[-1]))
            if grid_shape is None:
                grid_shape = current_shape
            elif current_shape != grid_shape:
                raise ValueError("backbone produced inconsistent patch grids")
            all_embeddings.append(patch_embeddings(features))
        return np.concatenate(all_embeddings), grid_shape  # type: ignore[arg-type]

    def fit(self, records: Iterable[MVTecFile]) -> np.ndarray:
        paths = [record.image for record in records if record.split == "train" and record.defect == "good"]
        embeddings, _ = self._embeddings(paths)
        return self.pipeline.fit(embeddings)

    def score(self, image: str | Path) -> ImageScore:
        path = Path(image)
        embeddings, grid_shape = self._embeddings([path])
        result = self.pipeline.score(embeddings, grid_shape)
        return ImageScore(path, result.score, result.heatmap, grid_shape)
