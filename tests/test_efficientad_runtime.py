import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.efficientad.runtime import EfficientADRuntimeError, NativeEfficientADRuntime


class EfficientADRuntimeTests(unittest.TestCase):
    def test_missing_teacher_is_rejected_before_model_use(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "bottle.pt"
            checkpoint.write_bytes(b"placeholder")
            with self.assertRaisesRegex(EfficientADRuntimeError, "teacher checkpoint not found"):
                NativeEfficientADRuntime({"bottle": checkpoint}, Path(directory) / "teacher.pth")

    def test_missing_category_checkpoint_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            teacher = Path(directory) / "teacher.pth"
            teacher.write_bytes(b"placeholder")
            with self.assertRaisesRegex(EfficientADRuntimeError, "category checkpoint"):
                NativeEfficientADRuntime({"bottle": Path(directory) / "bottle.pt"}, teacher)

    def test_category_bundle_is_loaded_once(self) -> None:
        try:
            import torch  # noqa: F401
        except ImportError:
            self.skipTest("torch is not installed in the system test interpreter")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            teacher = root / "teacher.pth"
            checkpoint = root / "bottle.pt"
            image = root / "image.png"
            teacher.write_bytes(b"teacher")
            checkpoint.write_bytes(b"checkpoint")
            image.write_bytes(b"image")
            with patch("app.efficientad.runtime.load_teacher"), patch("app.efficientad.runtime.load_model_bundle", return_value=object()) as load_bundle, patch("app.efficientad.runtime.infer_loaded", return_value=(0.1, object())):
                runtime = NativeEfficientADRuntime({"bottle": checkpoint}, teacher)
                with patch.object(runtime, "_checkpoint_payload", return_value={}):
                    runtime.score("bottle", image)
                    runtime.score("bottle", image)
                load_bundle.assert_called_once()

    def test_reload_invalidates_one_category(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            teacher = root / "teacher.pth"
            bottle = root / "bottle.pt"
            screw = root / "screw.pt"
            teacher.write_bytes(b"teacher")
            bottle.write_bytes(b"bottle")
            screw.write_bytes(b"screw")
            runtime = object.__new__(NativeEfficientADRuntime)
            runtime.checkpoints = {"bottle": bottle, "screw": screw}
            runtime._bundles = {"bottle": object(), "screw": object()}
            self.assertEqual(runtime.reload("bottle"), frozenset({"screw"}))
            self.assertEqual(runtime.reload(), frozenset())


if __name__ == "__main__":
    unittest.main()
