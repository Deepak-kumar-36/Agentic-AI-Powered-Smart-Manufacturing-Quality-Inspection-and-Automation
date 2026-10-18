from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

import numpy as np

from app.api import InspectionApi
from app.camera import CameraFrame
from app.phone_shadow import capture_and_submit
from app.persistence import InspectionStore


class FakeSource:
    def __init__(self, frame: CameraFrame | None):
        self.frame = frame

    def open(self) -> None:
        pass

    def read(self, timeout_ms: int):
        return self.frame

    def health(self):
        return {"camera_id": "fake"}

    def close(self) -> None:
        pass


class FakeModel:
    def score(self, category: str, image: str | Path):
        return type("Evidence", (), {"model_version": "test-model", "score": 0.1})()


class PhoneShadowTests(unittest.TestCase):
    def test_capture_and_submit_persists_server_decision(self) -> None:
        now = datetime.now(timezone.utc)
        frame = CameraFrame(np.zeros((64, 64, 3), dtype=np.uint8), now.isoformat(), "phone", 1, 64, 64)
        store = InspectionStore()
        from app.policy import DecisionPolicy

        api = InspectionApi(store, model=FakeModel(), policies={"bottle": DecisionPolicy("test-policy", frozenset({"test-model"}), 0.2, 0.8)}, image_root=Path(tempfile.gettempdir()))
        with tempfile.TemporaryDirectory() as directory:
            results = capture_and_submit(FakeSource(frame), api, category="bottle", image_dir=Path(directory))
        self.assertEqual(results[0]["outcome"], "PASS")
        self.assertEqual(len(store.list()), 1)
        store.close()

    def test_capture_failure_is_unverified_without_creating_inspection(self) -> None:
        store = InspectionStore()
        api = InspectionApi(store)
        with tempfile.TemporaryDirectory() as directory:
            results = capture_and_submit(FakeSource(None), api, category="bottle", image_dir=Path(directory))
        self.assertEqual(results[0]["outcome"], "UNVERIFIED")
        self.assertEqual(store.list(), [])
        store.close()


if __name__ == "__main__":
    unittest.main()
