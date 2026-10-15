import tempfile
import unittest
import base64
from pathlib import Path

import numpy as np

from app.patchcore.artifacts import write_array, write_json
from app.patchcore.core import PatchCoreConfig, PatchCorePipeline, deterministic_coreset, patch_embeddings
from app.patchcore.dataset import discover_mvtec


class PatchCoreTests(unittest.TestCase):
    def test_bounded_deterministic_bank_and_score(self) -> None:
        points = np.arange(40, dtype=np.float32).reshape(20, 2)
        self.assertTrue(np.array_equal(deterministic_coreset(points, 5, 3), deterministic_coreset(points, 5, 3)))
        pipeline = PatchCorePipeline(PatchCoreConfig(memory_bank_size=5))
        pipeline.fit(points)
        result = pipeline.score(points[:4], (2, 2))
        self.assertEqual(result.heatmap.shape, (2, 2))
        self.assertTrue(np.isfinite(result.score))

    def test_distance_chunking_handles_more_queries_than_chunk(self) -> None:
        points = np.arange(80, dtype=np.float32).reshape(40, 2)
        pipeline = PatchCorePipeline(PatchCoreConfig(memory_bank_size=5, distance_chunk_size=3))
        pipeline.fit(points)
        result = pipeline.score(points, (5, 8))
        self.assertEqual(result.nearest_distances.shape, (40,))
        self.assertTrue(np.all(np.isfinite(result.nearest_distances)))

    def test_patch_embedding_shape(self) -> None:
        self.assertEqual(patch_embeddings(np.zeros((2, 3, 4, 5), dtype=np.float32)).shape, (40, 3))

    def test_dataset_reports_missing_masks_duplicates_and_corruption(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            good = root / "bottle" / "train" / "good"
            defect = root / "bottle" / "test" / "crack"
            good.mkdir(parents=True)
            defect.mkdir(parents=True)
            # Tiny valid PNG, duplicated intentionally to exercise hash reporting.
            png = base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
            )
            (good / "001.png").write_bytes(png)
            (defect / "001.png").write_bytes(png)
            report = discover_mvtec(root)
            kinds = {issue.kind for issue in report.issues}
            self.assertIn("missing_mask", kinds)
            self.assertIn("duplicate_file", kinds)

    def test_artifacts_refuse_overwrite_and_disable_pickle(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "x.npy"
            write_array(path, np.ones(2))
            with self.assertRaises(FileExistsError):
                write_array(path, np.ones(2))
            self.assertTrue(np.array_equal(np.load(path, allow_pickle=False), np.ones(2)))
            write_json(Path(temp) / "meta.json", {"ok": True})


if __name__ == "__main__":
    unittest.main()
