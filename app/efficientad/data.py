from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
from typing import Iterable

from app.patchcore.dataset import EXPECTED_MVTEC_CATEGORIES, _image_ok, _sha256


@dataclass(frozen=True)
class ManifestRow:
    sample_id: str
    relative_path: str
    split: str
    label: int
    category: str
    mask_relative_path: str | None
    sha256: str


@dataclass(frozen=True)
class DatasetManifest:
    root: Path
    rows: tuple[ManifestRow, ...]
    dataset_id: str = "mvtec-ad"
    license: str = "CC BY-NC-SA 4.0"

    def __post_init__(self) -> None:
        if not self.rows:
            raise ValueError("manifest cannot be empty")
        ids = [row.sample_id for row in self.rows]
        if len(ids) != len(set(ids)):
            raise ValueError("manifest contains duplicate sample_id values")
        paths = [row.relative_path for row in self.rows]
        if len(paths) != len(set(paths)):
            raise ValueError("manifest contains duplicate image paths")
        if any(row.split not in {"train", "validation", "test"} for row in self.rows):
            raise ValueError("manifest contains an unsupported split")
        if any(row.label not in {0, 1} for row in self.rows):
            raise ValueError("labels must be 0 for good and 1 for anomalous")
        if not any(row.split == "train" and row.label == 0 for row in self.rows):
            raise ValueError("manifest has no normal training images")

    @property
    def categories(self) -> tuple[str, ...]:
        return tuple(sorted({row.category for row in self.rows}))

    def stable_json(self) -> str:
        payload = {"dataset_id": self.dataset_id, "license": self.license, "rows": [asdict(row) for row in self.rows]}
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    def digest(self) -> str:
        return hashlib.sha256(self.stable_json().encode()).hexdigest()

    def write(self, path: str | Path) -> None:
        destination = Path(path)
        if destination.exists():
            raise FileExistsError(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(self.stable_json() + "\n", encoding="utf-8")

    @classmethod
    def read(cls, path: str | Path, root: str | Path) -> "DatasetManifest":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        rows = tuple(ManifestRow(**row) for row in payload["rows"])
        return cls(Path(root).resolve(), rows, payload.get("dataset_id", "unknown"), payload.get("license", "unknown"))


def _safe_relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError(f"path escapes dataset root: {path}") from exc


def discover_mvtec_manifest(root: str | Path, categories: Iterable[str] | None = None) -> DatasetManifest:
    """Create a deterministic, hashed manifest from an extracted MVTec tree."""
    dataset_root = Path(root).expanduser().resolve()
    if not dataset_root.is_dir():
        raise ValueError(f"dataset root does not exist or is not a directory: {dataset_root}")
    requested = set(categories) if categories is not None else set(EXPECTED_MVTEC_CATEGORIES)
    if not requested <= EXPECTED_MVTEC_CATEGORIES:
        raise ValueError(f"unsupported MVTec category: {sorted(requested - EXPECTED_MVTEC_CATEGORIES)}")
    rows: list[ManifestRow] = []
    for category in sorted(requested):
        base = dataset_root / category
        train = base / "train" / "good"
        test = base / "test"
        if not train.is_dir() or not test.is_dir():
            raise ValueError(f"invalid MVTec layout for category {category}")
        images = sorted(train.glob("*.png"))
        split_index = max(1, int(len(images) * 0.2))
        for index, image in enumerate(images):
            ok, detail = _image_ok(image)
            if not ok:
                raise ValueError(f"invalid image {image}: {detail}")
            split = "validation" if index < split_index else "train"
            relative = _safe_relative(dataset_root, image)
            rows.append(ManifestRow(f"{category}:train:{image.stem}", relative, split, 0, category, None, _sha256(image)))
        for defect_dir in sorted(path for path in test.iterdir() if path.is_dir() and path.name != "good"):
            for image in sorted(defect_dir.glob("*.png")):
                ok, detail = _image_ok(image)
                if not ok:
                    raise ValueError(f"invalid image {image}: {detail}")
                mask = base / "ground_truth" / defect_dir.name / f"{image.stem}_mask.png"
                if not mask.is_file():
                    raise ValueError(f"missing ground-truth mask: {mask}")
                mask_ok, mask_detail = _image_ok(mask)
                if not mask_ok:
                    raise ValueError(f"invalid mask {mask}: {mask_detail}")
                rows.append(ManifestRow(f"{category}:test:{defect_dir.name}:{image.stem}", _safe_relative(dataset_root, image), "test", 1, category, _safe_relative(dataset_root, mask), _sha256(image)))
        for image in sorted((test / "good").glob("*.png")):
            ok, detail = _image_ok(image)
            if not ok:
                raise ValueError(f"invalid image {image}: {detail}")
            rows.append(ManifestRow(f"{category}:test:good:{image.stem}", _safe_relative(dataset_root, image), "test", 0, category, None, _sha256(image)))
    return DatasetManifest(dataset_root, tuple(rows))
