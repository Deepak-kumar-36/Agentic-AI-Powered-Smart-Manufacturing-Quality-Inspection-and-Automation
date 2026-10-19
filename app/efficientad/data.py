from __future__ import annotations

from dataclasses import asdict, dataclass
import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from app.patchcore.dataset import EXPECTED_MVTEC_CATEGORIES, IMAGE_SUFFIXES, _image_ok, _sha256


@dataclass(frozen=True)
class ManifestRow:
    identifier: str
    path: str
    category: str
    label: int | None
    defect_type: str | None
    physical_sample_id: str | None
    capture_session: str | None
    camera_id: str | None
    width: int | None
    height: int | None
    split: str
    mask_path: str | None
    sha256: str

    # Compatibility names used by the original MVTec manifest consumers.
    @property
    def sample_id(self) -> str:
        return self.identifier

    @property
    def relative_path(self) -> str:
        return self.path

    @property
    def mask_relative_path(self) -> str | None:
        return self.mask_path


@dataclass(frozen=True)
class DatasetManifest:
    root: Path
    rows: tuple[ManifestRow, ...]
    dataset_id: str = "mvtec-ad"
    license: str = "CC BY-NC-SA 4.0"

    def __post_init__(self) -> None:
        if not self.rows:
            raise ValueError("manifest cannot be empty")
        ids = [row.identifier for row in self.rows]
        if len(ids) != len(set(ids)):
            raise ValueError("manifest contains duplicate sample_id values")
        paths = [row.path for row in self.rows]
        if len(paths) != len(set(paths)):
            raise ValueError("manifest contains duplicate image paths")
        if any(row.split not in {"train", "validation", "test"} for row in self.rows):
            raise ValueError("manifest contains an unsupported split")
        if any(row.label is not None and row.label not in {0, 1} for row in self.rows):
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
        rows = tuple(_row_from_payload(row) for row in payload["rows"])
        return cls(Path(root).resolve(), rows, payload.get("dataset_id", "unknown"), payload.get("license", "unknown"))


def _safe_relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError(f"path escapes dataset root: {path}") from exc


@dataclass(frozen=True)
class CapsuleDiscoveryConfig:
    """Filesystem and metadata conventions for a captured capsule dataset."""

    category: str = "capsule"
    metadata_filename: str | None = "metadata.json"
    require_masks: bool = False
    image_suffixes: frozenset[str] = IMAGE_SUFFIXES


@dataclass(frozen=True)
class ManifestIssue:
    kind: str
    identifier: str | None
    detail: str


def _row_from_payload(payload: Mapping[str, Any]) -> ManifestRow:
    """Read both the current schema and manifests emitted by the old MVTec code."""
    if "identifier" in payload:
        return ManifestRow(**payload)
    return ManifestRow(
        identifier=payload["sample_id"], path=payload["relative_path"], category=payload["category"],
        label=payload.get("label"), defect_type=payload.get("defect_type"),
        physical_sample_id=payload.get("physical_sample_id"), capture_session=payload.get("capture_session"),
        camera_id=payload.get("camera_id"), width=payload.get("width"), height=payload.get("height"),
        split=payload["split"], mask_path=payload.get("mask_relative_path"), sha256=payload["sha256"],
    )


def _metadata(root: Path, filename: str | None) -> dict[str, dict[str, Any]]:
    if not filename:
        return {}
    path = root / filename
    if not path.is_file():
        return {}
    if path.suffix.lower() == ".csv":
        with path.open(newline="", encoding="utf-8") as stream:
            rows = list(csv.DictReader(stream))
    else:
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload if isinstance(payload, list) else payload.get("rows", payload)
        if isinstance(rows, Mapping):
            rows = [dict(value, path=key) for key, value in rows.items() if isinstance(value, Mapping)]
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        key = str(row.get("path") or row.get("identifier") or "")
        if key:
            normalized = dict(row)
            for field in ("label", "width", "height"):
                if normalized.get(field) not in (None, ""):
                    try:
                        normalized[field] = int(normalized[field])
                    except (TypeError, ValueError):
                        pass
            result[key] = normalized
    return result


def validate_manifest(manifest: DatasetManifest) -> tuple[ManifestIssue, ...]:
    """Validate content and split integrity without changing the manifest."""
    issues: list[ManifestIssue] = []
    hashes: dict[str, str] = {}
    groups: dict[tuple[str, str], set[str]] = {}
    for row in manifest.rows:
        image = manifest.root / row.path
        if row.label not in {0, 1}:
            issues.append(ManifestIssue("missing_label", row.identifier, "label must be 0 (good) or 1 (defect)"))
        ok, detail = _image_ok(image)
        if not ok:
            issues.append(ManifestIssue("decode_failure", row.identifier, detail))
            continue
        if row.sha256 in hashes and hashes[row.sha256] != row.identifier:
            issues.append(ManifestIssue("duplicate_hash", row.identifier, f"same sha256 as {hashes[row.sha256]}"))
        else:
            hashes[row.sha256] = row.identifier
        for field, value in (("physical_sample_id", row.physical_sample_id), ("capture_session", row.capture_session)):
            if value:
                key = (field, value)
                groups.setdefault(key, set()).add(row.split)
    for (field, value), splits in groups.items():
        if len(splits) > 1:
            issues.append(ManifestIssue("split_leakage", None, f"{field}={value!r} occurs in splits: {', '.join(sorted(splits))}"))
    return tuple(issues)


def discover_real_capsule_manifest(root: str | Path, config: CapsuleDiscoveryConfig | None = None) -> DatasetManifest:
    """Discover ``train/validation/test`` capsule data and build a hashed manifest.

    The root may be the category directory or a parent containing ``capsule/``.
    Optional ``metadata.json``/CSV rows are keyed by relative ``path`` or
    ``identifier`` and enrich provenance fields; no image or metadata is invented.
    """
    settings = config or CapsuleDiscoveryConfig()
    dataset_root = Path(root).expanduser().resolve()
    category_root = dataset_root / settings.category
    if (dataset_root / "train").is_dir() and not category_root.is_dir():
        category_root = dataset_root
        dataset_root = category_root.parent
    if not category_root.is_dir():
        raise ValueError(f"dataset root does not contain category directory: {category_root}")
    metadata = _metadata(category_root, settings.metadata_filename) or _metadata(dataset_root, settings.metadata_filename)
    rows: list[ManifestRow] = []
    for split in ("train", "validation", "test"):
        split_root = category_root / split
        if not split_root.is_dir():
            raise ValueError(f"missing split directory: {split_root}")
        for label_dir in sorted(p for p in split_root.iterdir() if p.is_dir()):
            if label_dir.name == "good":
                label, defect_type = 0, None
                defect_dirs = (label_dir,)
            elif label_dir.name == "defects":
                label, defect_type = 1, None
                defect_dirs = tuple(p for p in sorted(label_dir.iterdir()) if p.is_dir())
            else:
                raise ValueError(f"unexpected directory under {split}: {label_dir.name}")
            for defect_dir in defect_dirs:
                for image in sorted(p for p in defect_dir.iterdir() if p.suffix.lower() in settings.image_suffixes):
                    relative = _safe_relative(dataset_root, image)
                    ok, detail = _image_ok(image)
                    if not ok:
                        raise ValueError(f"invalid image {image}: {detail}")
                    with_image = metadata.get(relative, metadata.get(_safe_relative(category_root, image), {}))
                    actual_defect = defect_type or defect_dir.name
                    mask = with_image.get("mask_path")
                    if mask is None and label:
                        candidate = category_root / "masks" / split / actual_defect / f"{image.stem}_mask{image.suffix}"
                        if candidate.is_file():
                            mask = _safe_relative(dataset_root, candidate)
                        elif settings.require_masks:
                            raise ValueError(f"missing mask for {image}")
                    with_image = dict(with_image)
                    with_image.setdefault("label", label)
                    with_image.setdefault("defect_type", actual_defect if label else None)
                    try:
                        from PIL import Image
                        with Image.open(image) as opened:
                            width, height = opened.size
                    except Exception:
                        width = height = None
                    rows.append(ManifestRow(
                        identifier=str(with_image.get("identifier") or f"{settings.category}:{split}:{actual_defect}:{image.stem}"),
                        path=relative, category=settings.category, label=with_image.get("label"),
                        defect_type=with_image.get("defect_type"), physical_sample_id=with_image.get("physical_sample_id"),
                        capture_session=with_image.get("capture_session"), camera_id=with_image.get("camera_id"),
                        width=with_image.get("width", width), height=with_image.get("height", height), split=split,
                        mask_path=mask, sha256=_sha256(image),
                    ))
    manifest = DatasetManifest(dataset_root, tuple(rows), dataset_id=f"real-{settings.category}", license="unspecified")
    issues = validate_manifest(manifest)
    if issues:
        raise ValueError("manifest validation failed: " + "; ".join(issue.detail for issue in issues))
    return manifest


discover_dataset_manifest = discover_real_capsule_manifest


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
            rows.append(ManifestRow(
                identifier=f"{category}:train:{image.stem}", path=relative, category=category, label=0,
                defect_type=None, physical_sample_id=None, capture_session=None, camera_id=None,
                width=None, height=None, split=split, mask_path=None, sha256=_sha256(image),
            ))
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
                rows.append(ManifestRow(
                    identifier=f"{category}:test:{defect_dir.name}:{image.stem}", path=_safe_relative(dataset_root, image),
                    category=category, label=1, defect_type=defect_dir.name, physical_sample_id=None,
                    capture_session=None, camera_id=None, width=None, height=None, split="test",
                    mask_path=_safe_relative(dataset_root, mask), sha256=_sha256(image),
                ))
        for image in sorted((test / "good").glob("*.png")):
            ok, detail = _image_ok(image)
            if not ok:
                raise ValueError(f"invalid image {image}: {detail}")
            rows.append(ManifestRow(
                identifier=f"{category}:test:good:{image.stem}", path=_safe_relative(dataset_root, image),
                category=category, label=0, defect_type=None, physical_sample_id=None, capture_session=None,
                camera_id=None, width=None, height=None, split="test", mask_path=None, sha256=_sha256(image),
            ))
    return DatasetManifest(dataset_root, tuple(rows))
