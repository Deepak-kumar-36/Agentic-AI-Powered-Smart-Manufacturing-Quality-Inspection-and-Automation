"""Strict, filesystem-only MVTec AD dataset discovery.

Discovery never downloads or invents samples.  It returns issues so callers can
decide whether an incomplete dataset is acceptable for their workflow.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Iterable


IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"})
EXPECTED_MVTEC_CATEGORIES = frozenset(
    {
        "bottle", "cable", "capsule", "carpet", "grid", "hazelnut", "leather",
        "metal_nut", "pill", "screw", "tile", "toothbrush", "transistor", "wood", "zipper",
    }
)


@dataclass(frozen=True)
class MVTecFile:
    category: str
    split: str
    defect: str
    image: Path
    mask: Path | None
    sha256: str


@dataclass(frozen=True)
class DatasetIssue:
    kind: str
    path: Path
    detail: str
    category: str | None = None


@dataclass(frozen=True)
class MVTecDatasetReport:
    root: Path
    categories: tuple[str, ...]
    files: tuple[MVTecFile, ...]
    issues: tuple[DatasetIssue, ...]
    duplicate_hashes: tuple[tuple[str, tuple[Path, ...]], ...]

    @property
    def is_valid(self) -> bool:
        return not self.issues

    @property
    def train_files(self) -> tuple[MVTecFile, ...]:
        return tuple(item for item in self.files if item.split == "train")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _image_ok(path: Path) -> tuple[bool, str]:
    if not path.is_file():
        return False, "file does not exist"
    if path.stat().st_size == 0:
        return False, "file is empty"
    try:
        from PIL import Image  # type: ignore[import-not-found]
    except ImportError:
        return True, "Pillow unavailable; only non-empty validation performed"
    try:
        with Image.open(path) as image:
            image.verify()
    except Exception as exc:  # Pillow raises several format-specific errors.
        return False, f"image decode failed: {exc}"
    return True, ""


def discover_mvtec(root: str | Path, categories: Iterable[str] | None = None) -> MVTecDatasetReport:
    """Discover an MVTec AD tree and report every structural/data problem."""
    dataset_root = Path(root).expanduser()
    issues: list[DatasetIssue] = []
    if not dataset_root.exists():
        return MVTecDatasetReport(dataset_root, (), (), (DatasetIssue("missing_root", dataset_root, "root does not exist"),), ())
    if not dataset_root.is_dir():
        return MVTecDatasetReport(dataset_root, (), (), (DatasetIssue("invalid_root", dataset_root, "root is not a directory"),), ())

    requested = tuple(sorted(set(categories))) if categories is not None else None
    found = tuple(sorted(path.name for path in dataset_root.iterdir() if path.is_dir()))
    category_names = tuple(name for name in found if requested is None or name in requested)
    for name in category_names:
        if name not in EXPECTED_MVTEC_CATEGORIES:
            issues.append(DatasetIssue("unexpected_category", dataset_root / name, "not an official MVTec AD category", name))
    for name in requested or ():
        if name not in found:
            issues.append(DatasetIssue("missing_category", dataset_root / name, "category directory is missing", name))

    records: list[MVTecFile] = []
    hash_paths: dict[str, list[Path]] = {}
    for category in category_names:
        base = dataset_root / category
        train_good = base / "train" / "good"
        if not train_good.is_dir():
            issues.append(DatasetIssue("missing_layout", train_good, "train/good directory is missing", category))
        test_root = base / "test"
        if not test_root.is_dir():
            issues.append(DatasetIssue("missing_layout", test_root, "test directory is missing", category))
        # MVTec stores train/good images directly under train/good, while test
        # images are nested under test/<defect-or-good>.
        split_dirs = (("train", (("good", train_good),)), ("test", tuple(
            (directory.name, directory) for directory in sorted(test_root.iterdir()) if directory.is_dir()
        ) if test_root.is_dir() else ()))
        for split, defect_dirs in split_dirs:
            for defect, defect_dir in defect_dirs:
                for image in sorted(p for p in defect_dir.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES):
                    ok, detail = _image_ok(image)
                    if not ok:
                        issues.append(DatasetIssue("corrupt_file", image, detail, category))
                        continue
                    digest = _sha256(image)
                    hash_paths.setdefault(digest, []).append(image)
                    mask = None
                    if split == "test" and defect != "good":
                        mask = base / "ground_truth" / defect / f"{image.stem}_mask.png"
                        if not mask.exists():
                            issues.append(DatasetIssue("missing_mask", mask, "ground-truth mask is missing", category))
                        else:
                            mask_ok, mask_detail = _image_ok(mask)
                            if not mask_ok:
                                issues.append(DatasetIssue("corrupt_mask", mask, mask_detail, category))
                    records.append(MVTecFile(category, split, defect, image, mask, digest))
    duplicates = tuple(sorted((digest, tuple(paths)) for digest, paths in hash_paths.items() if len(paths) > 1))
    for digest, paths in duplicates:
        issues.append(DatasetIssue("duplicate_file", paths[0], f"sha256 {digest} also occurs at {len(paths)-1} other path(s)"))
    return MVTecDatasetReport(dataset_root, category_names, tuple(records), tuple(issues), duplicates)


class MVTecDatasetLoader:
    """Small state-free loader facade useful to applications and tests."""

    def __init__(self, root: str | Path, categories: Iterable[str] | None = None) -> None:
        self.root = Path(root)
        self.categories = tuple(categories) if categories is not None else None

    def scan(self) -> MVTecDatasetReport:
        return discover_mvtec(self.root, self.categories)
