import tempfile
import unittest
from pathlib import Path

from PIL import Image

from app.efficientad.data import (
    CapsuleDiscoveryConfig,
    DatasetManifest,
    ManifestRow,
    discover_real_capsule_manifest,
    discover_mvtec_manifest,
    validate_manifest,
)


class EfficientADDataTests(unittest.TestCase):
    @staticmethod
    def _write_layout(root: Path) -> None:
        for path in (
            root / "train" / "good" / "train-001.png",
            root / "validation" / "good" / "val-001.png",
            root / "validation" / "defects" / "scratch" / "val-002.png",
            root / "test" / "good" / "test-001.png",
            root / "test" / "defects" / "scratch" / "test-002.png",
        ):
            path.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (7, 5), (128 + len(str(path)), 128, 128)).save(path)

    def test_real_capsule_layout_emits_schema_and_dimensions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            category = Path(directory) / "capsule"
            self._write_layout(category)
            manifest = discover_real_capsule_manifest(category, CapsuleDiscoveryConfig(metadata_filename=None))
            self.assertEqual({row.split for row in manifest.rows}, {"train", "validation", "test"})
            defect = next(row for row in manifest.rows if row.label == 1)
            self.assertEqual((defect.defect_type, defect.width, defect.height), ("scratch", 7, 5))
            self.assertIsNone(defect.physical_sample_id)
            self.assertEqual(validate_manifest(manifest), ())

    def test_validation_reports_missing_label_duplicate_hash_and_group_leakage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first.png"
            second = root / "second.png"
            Image.new("RGB", (2, 2), (1, 2, 3)).save(first)
            first_bytes = first.read_bytes()
            second.write_bytes(first_bytes)
            digest = __import__("hashlib").sha256(first_bytes).hexdigest()
            rows = (
                ManifestRow("one", "first.png", "capsule", 0, None, "unit-1", "session-1", None, 2, 2, "train", None, digest),
                ManifestRow("two", "second.png", "capsule", None, None, "unit-1", "session-1", None, 2, 2, "test", None, digest),
            )
            issues = validate_manifest(DatasetManifest(root, rows))
            kinds = {issue.kind for issue in issues}
            self.assertTrue({"missing_label", "duplicate_hash", "split_leakage"} <= kinds)

    def test_discovery_fails_on_decode_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            category = Path(directory) / "capsule"
            (category / "train" / "good").mkdir(parents=True)
            (category / "validation" / "good").mkdir(parents=True)
            (category / "test" / "good").mkdir(parents=True)
            (category / "train" / "good" / "broken.png").write_bytes(b"not an image")
            with self.assertRaisesRegex(ValueError, "invalid image"):
                discover_real_capsule_manifest(category)

    def test_manifest_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "bottle"
            (root / "train" / "good").mkdir(parents=True)
            (root / "test" / "good").mkdir(parents=True)
            (root / "test" / "scratch").mkdir(parents=True)
            (root / "ground_truth" / "scratch").mkdir(parents=True)
            for path in [root / "train" / "good" / "001.png", root / "train" / "good" / "002.png", root / "test" / "good" / "001.png", root / "test" / "scratch" / "001.png", root / "ground_truth" / "scratch" / "001_mask.png"]:
                Image.new("RGB", (4, 4), (128, 128, 128)).save(path)
            first = discover_mvtec_manifest(Path(directory), ["bottle"])
            second = discover_mvtec_manifest(Path(directory), ["bottle"])
            self.assertEqual(first.digest(), second.digest())
            self.assertEqual(len(first.rows), 4)

    def test_missing_mask_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "bottle"
            (root / "train" / "good").mkdir(parents=True)
            (root / "test" / "scratch").mkdir(parents=True)
            Image.new("RGB", (4, 4)).save(root / "train" / "good" / "001.png")
            Image.new("RGB", (4, 4)).save(root / "test" / "scratch" / "001.png")
            with self.assertRaisesRegex(ValueError, "mask"):
                discover_mvtec_manifest(Path(directory), ["bottle"])
