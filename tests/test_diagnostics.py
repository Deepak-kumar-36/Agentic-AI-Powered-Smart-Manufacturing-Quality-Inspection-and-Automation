import tempfile
import unittest
from pathlib import Path

from app.efficientad.diagnostics import diagnose_image


class _Bundle:
    pass


class DiagnosticTests(unittest.TestCase):
    def test_diagnostic_requires_thresholds_for_a_decision(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            image = Path(temp) / "capsule.ppm"
            image.write_bytes(b"P6\n1 1\n255\n\xff\x00\x00")
            # Patch the native inference boundary so this test remains dependency-free.
            import app.efficientad.diagnostics as diagnostics
            original = diagnostics.infer_loaded
            original_overlay = diagnostics.overlay_image
            original_transform = diagnostics.image_transform
            diagnostics.infer_loaded = lambda *_args: (0.4, __import__("numpy").zeros((1, 1), dtype="float32"))
            diagnostics.overlay_image = lambda *_args: None
            diagnostics.image_transform = lambda: lambda value: __import__("numpy").zeros((3, 256, 256), dtype="float32")
            try:
                report = diagnose_image(_Bundle(), image, Path(temp) / "out", model_version="test-v1")
                self.assertEqual(report.outcome, "UNVERIFIED")
                self.assertEqual(report.reason_codes, ["THRESHOLDS_NOT_PROVIDED"])
                self.assertEqual(report.preprocessed_shape, (3, 256, 256))
                self.assertTrue(Path(report.heatmap_path).is_file())
                self.assertTrue((Path(temp) / "out" / "capsule.diagnostic.json").is_file())
            finally:
                diagnostics.infer_loaded = original
                diagnostics.overlay_image = original_overlay
                diagnostics.image_transform = original_transform


if __name__ == "__main__":
    unittest.main()
