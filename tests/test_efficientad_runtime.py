import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
