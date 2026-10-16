from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json


@dataclass(frozen=True)
class EfficientADConfig:
    """All release-relevant training and preprocessing settings."""

    model_id: str = "efficientad-s"
    model_size: str = "small"
    image_size: tuple[int, int] = (256, 256)
    batch_size: int = 32
    epochs: int = 100
    learning_rate: float = 1e-4
    weight_decay: float = 1e-5
    seed: int = 42
    validation_fraction: float = 0.2
    device: str = "auto"
    num_workers: int = 2
    implementation: str = "anomalib"
    implementation_version: str = "2.2.0"
    preprocess_version: str = "efficientad_preprocess_v1"

    def __post_init__(self) -> None:
        if self.model_size != "small":
            raise ValueError("this project currently supports EfficientAD-S only")
        if len(self.image_size) != 2 or any(value < 32 for value in self.image_size):
            raise ValueError("image_size must contain two dimensions >= 32")
        if self.batch_size < 1 or self.epochs < 1 or self.num_workers < 0:
            raise ValueError("batch_size and epochs must be positive; num_workers cannot be negative")
        if not 0 < self.learning_rate or not 0 <= self.weight_decay or not 0 < self.validation_fraction < 1:
            raise ValueError("learning rate, weight decay, and validation fraction are invalid")
        if self.seed < 0:
            raise ValueError("seed must be non-negative")

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["image_size"] = list(self.image_size)
        return payload

    def stable_json(self) -> str:
        return json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"))

    def digest(self) -> str:
        return hashlib.sha256(self.stable_json().encode()).hexdigest()
