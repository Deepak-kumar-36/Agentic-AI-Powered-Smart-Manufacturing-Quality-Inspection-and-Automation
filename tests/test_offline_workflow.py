from pathlib import Path
import tempfile
import unittest

from app.api import InspectionApi
from app.offline_workflow import FileFrameSource, OfflineInspectionWorkflow
from app.persistence import InspectionStore
from app.policy import DecisionPolicy


FIXTURES = Path(__file__).parent / "fixtures" / "inspection"


class _Evidence:
    model_version = "mock-file-v1"

    def __init__(self, score: float) -> None:
        self.score = score


class _MockFileModel:
    def score(self, _category: str, image: str | Path) -> _Evidence:
        return _Evidence(0.9 if "anomalous" in Path(image).name else 0.1)


def _api(store: InspectionStore, image_root: Path, model: object | None = None) -> InspectionApi:
    return InspectionApi(
        store,
        model=model,
        policies={"bottle": DecisionPolicy("mock-policy-v1", frozenset({"mock-file-v1"}), 0.2, 0.8)},
        image_root=image_root,
    )


class OfflineWorkflowTests(unittest.TestCase):
    def test_normal_stored_image_is_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            api = _api(InspectionStore(), root, _MockFileModel())
            try:
                result = OfflineInspectionWorkflow(api, FileFrameSource(FIXTURES / "normal.ppm"), "bottle", root).run("normal-1")
                self.assertEqual(result["outcome"], "PASS")
            finally:
                api.store.close()

    def test_anomalous_stored_image_is_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            api = _api(InspectionStore(), root, _MockFileModel())
            try:
                result = OfflineInspectionWorkflow(api, FileFrameSource(FIXTURES / "anomalous.ppm"), "bottle", root).run("anomaly-1")
                self.assertEqual(result["outcome"], "FAIL")
            finally:
                api.store.close()

    def test_corrupt_stored_image_is_unverified(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            api = _api(InspectionStore(), root, _MockFileModel())
            try:
                result = OfflineInspectionWorkflow(api, FileFrameSource(FIXTURES / "corrupt.png"), "bottle", root).run("corrupt-1")
                self.assertEqual(result["outcome"], "UNVERIFIED")
                self.assertEqual(result["reason_codes"], ["IMAGE_INVALID"])
            finally:
                api.store.close()

    def test_missing_model_is_unverified(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            api = _api(InspectionStore(), root)
            try:
                result = OfflineInspectionWorkflow(api, FileFrameSource(FIXTURES / "normal.ppm"), "bottle", root).run("missing-model-1")
                self.assertEqual(result["outcome"], "UNVERIFIED")
                self.assertEqual(result["reason_codes"], ["MODEL_NOT_READY"])
            finally:
                api.store.close()

    def test_unsupported_category_is_unverified(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            api = _api(InspectionStore(), root, _MockFileModel())
            try:
                result = OfflineInspectionWorkflow(api, FileFrameSource(FIXTURES / "normal.ppm"), "cable", root).run("unsupported-1")
                self.assertEqual(result["outcome"], "UNVERIFIED")
                self.assertEqual(result["reason_codes"], ["UNSUPPORTED_CATEGORY"])
            finally:
                api.store.close()

    def test_decision_survives_api_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db = root / "inspection.sqlite3"
            first_store = InspectionStore(db)
            first_api = _api(first_store, root, _MockFileModel())
            first = OfflineInspectionWorkflow(first_api, FileFrameSource(FIXTURES / "normal.ppm"), "bottle", root).run("restart-1")
            inspection_id = first["inspection_id"]
            first_store.close()

            reopened = InspectionStore(db)
            second_api = _api(reopened, root, _MockFileModel())
            try:
                status, loaded = second_api.handle("GET", f"/api/v1/inspections/{inspection_id}")
                self.assertEqual(status, 200)
                self.assertEqual(loaded["outcome"], "PASS")
                self.assertEqual(len(reopened.events(inspection_id)), 2)
            finally:
                reopened.close()


if __name__ == "__main__":
    unittest.main()
