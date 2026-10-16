import tempfile
import unittest
from pathlib import Path

from PIL import Image

from app.efficientad.data import discover_mvtec_manifest


class EfficientADDataTests(unittest.TestCase):
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
