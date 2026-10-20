import json
import base64
from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timezone
import numpy as np

from app.api import InspectionApi
from app.persistence import InspectionStore
from app.policy import DecisionPolicy


class FakeEvidence:
    model_version = "efficientad-s-native-v1"

    def __init__(self, score: float, heatmap=None) -> None:
        self.score = score
        self.heatmap = heatmap


class FakeModel:
    def __init__(self, score: float) -> None:
        self.score_value = score

    def score(self, _category: str, _image: str | Path) -> FakeEvidence:
        return FakeEvidence(self.score_value)

    def reload(self, _category: str | None = None) -> set[str]:
        return set()


class FakeCamera:
    def __init__(self, frame=None, error=None) -> None:
        self.frame = frame
        self.error = error
        self.opened = False

    def open(self) -> None:
        if self.error:
            raise OSError(self.error)
        self.opened = True

    def read(self, _timeout_ms: int):
        return self.frame

    def health(self):
        return {"camera_id": "fake", "open": self.opened, "last_error": None}

    def close(self) -> None:
        self.opened = False


class InspectionApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.api = InspectionApi(InspectionStore())

    def tearDown(self) -> None:
        self.api.store.close()

    def test_health_and_readiness_are_explicit(self) -> None:
        status, live = self.api.handle("GET", "/health/live")
        self.assertEqual(status, 200)
        self.assertEqual(live["status"], "ok")
        status, ready = self.api.handle("GET", "/health/ready")
        self.assertEqual(status, 200)
        self.assertEqual(ready["components"]["model"], "not_ready")

    def test_metadata_is_honestly_unavailable_without_provider(self) -> None:
        status, payload = self.api.handle("GET", "/api/v1/system/metadata")
        self.assertEqual(status, 200)
        self.assertEqual(payload, {"available": False, "reason": "METADATA_NOT_CONFIGURED"})

    def test_metadata_is_returned_when_provider_is_configured(self) -> None:
        api = InspectionApi(
            InspectionStore(),
            metadata_provider=lambda: {
                "categories": ["bottle"],
                "model_versions": ["efficientad-s-native-v1"],
                "qualification": {"status": "QUALIFIED"},
                "training_summary": [{"category": "bottle", "samples": 12}],
                "artifact_path": "/srv/private/checkpoint.pt",
                "api_key": "do-not-return",
            },
        )
        try:
            status, payload = api.handle("GET", "/api/v1/system/metadata")
            self.assertEqual(status, 200)
            self.assertTrue(payload["available"])
            self.assertEqual(payload["categories"], ["bottle"])
            self.assertEqual(payload["training_summary"][0]["samples"], 12)
            self.assertNotIn("artifact_path", payload)
            self.assertNotIn("api_key", payload)
        finally:
            api.store.close()

    def test_inspection_is_persisted_unverified_when_model_unavailable(self) -> None:
        status, record = self.api.handle(
            "POST",
            "/api/v1/inspections",
            json.dumps({"category": "bottle", "source": "operator"}).encode(),
            {"Idempotency-Key": "api-test-1"},
        )
        self.assertEqual(status, 201)
        self.assertEqual(record["outcome"], "UNVERIFIED")
        self.assertEqual(record["reason_codes"], ["MODEL_NOT_READY"])
        self.assertEqual(self.api.handle("GET", f"/api/v1/inspections/{record['inspection_id']}")[1]["outcome"], "UNVERIFIED")

    def test_duplicate_request_is_idempotent(self) -> None:
        body = json.dumps({"category": "bottle"}).encode()
        first = self.api.handle("POST", "/api/v1/inspections", body, {"Idempotency-Key": "same"})[1]
        second = self.api.handle("POST", "/api/v1/inspections", body, {"Idempotency-Key": "same"})[1]
        self.assertEqual(first["inspection_id"], second["inspection_id"])

    def test_invalid_requests_are_rejected(self) -> None:
        with self.assertRaisesRegex(Exception, "Idempotency-Key"):
            self.api.handle("POST", "/api/v1/inspections", b"{}")
        with self.assertRaisesRegex(Exception, "category"):
            self.api.handle("POST", "/api/v1/inspections", b"{}", {"Idempotency-Key": "bad"})

    def test_client_cannot_supply_a_decision_or_score(self) -> None:
        body = json.dumps({"category": "bottle", "outcome": "PASS", "score": 0.0}).encode()
        record = self.api.handle("POST", "/api/v1/inspections", body, {"Idempotency-Key": "untrusted"})[1]
        self.assertEqual(record["outcome"], "UNVERIFIED")

    def test_configured_model_records_policy_decision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "sample.png"
            image.write_bytes(b"image-placeholder")
            api = InspectionApi(
                InspectionStore(),
                model=FakeModel(0.1),
                policies={"bottle": DecisionPolicy("policy-1", frozenset({"efficientad-s-native-v1"}), 0.2, 0.8)},
                image_root=directory,
            )
            try:
                status, record = api.handle(
                    "POST", "/api/v1/inspections",
                    json.dumps({"category": "bottle", "image_path": "sample.png"}).encode(),
                    {"Idempotency-Key": "model-backed"},
                )
                self.assertEqual(status, 201)
                self.assertEqual(record["outcome"], "PASS")
                self.assertEqual(record["model_version"], "efficientad-s-native-v1")
                self.assertEqual(record["score"], 0.1)
            finally:
                api.store.close()

    def test_model_request_rejects_path_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            api = InspectionApi(
                InspectionStore(),
                model=FakeModel(0.1),
                policies={"bottle": DecisionPolicy("policy-1", frozenset({"efficientad-s-native-v1"}), 0.2, 0.8)},
                image_root=directory,
            )
            try:
                record = api.handle(
                    "POST", "/api/v1/inspections",
                    json.dumps({"category": "bottle", "image_path": "../outside.png"}).encode(),
                    {"Idempotency-Key": "path-escape"},
                )[1]
                self.assertEqual(record["outcome"], "UNVERIFIED")
                self.assertEqual(record["reason_codes"], ["IMAGE_INVALID"])
            finally:
                api.store.close()

    def test_image_upload_stores_valid_image_under_image_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            api = InspectionApi(InspectionStore(), image_root=directory)
            try:
                image_bytes = b"P6\n1 1\n255\n\xff\x00\x00"
                status, payload = api.handle(
                    "POST", "/api/v1/images",
                    json.dumps({"filename": "sample.ppm", "data_base64": base64.b64encode(image_bytes).decode()}).encode(),
                )
                self.assertEqual(status, 201)
                self.assertTrue((Path(directory) / payload["image_path"]).is_file())
            finally:
                api.store.close()

    def test_image_upload_rejects_corrupt_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            api = InspectionApi(InspectionStore(), image_root=directory)
            try:
                with self.assertRaisesRegex(Exception, "valid base64 image"):
                    api.handle("POST", "/api/v1/images", json.dumps({"filename": "bad.png", "data_base64": base64.b64encode(b"not-image").decode()}).encode())
            finally:
                api.store.close()

    def test_image_upload_rejects_oversized_request(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            api = InspectionApi(InspectionStore(), image_root=directory)
            try:
                with self.assertRaisesRegex(Exception, "12 MiB"):
                    api.handle("POST", "/api/v1/images", b"x" * (12 * 1024 * 1024 + 1))
            finally:
                api.store.close()

    def test_unsupported_category_is_unverified_with_configured_model(self) -> None:
        api = InspectionApi(
            InspectionStore(),
            model=FakeModel(0.1),
            policies={"bottle": DecisionPolicy("policy-1", frozenset({"efficientad-s-native-v1"}), 0.2, 0.8)},
        )
        try:
            record = api.handle(
                "POST", "/api/v1/inspections", json.dumps({"category": "cable"}).encode(),
                {"Idempotency-Key": "unsupported-category"},
            )[1]
            self.assertEqual(record["outcome"], "UNVERIFIED")
            self.assertEqual(record["reason_codes"], ["UNSUPPORTED_CATEGORY"])
            self.assertIsNone(record["score"])
        finally:
            api.store.close()

    def test_missing_heatmap_is_reported_without_fabricating_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "sample.png"
            image.write_bytes(b"image-placeholder")
            api = InspectionApi(
                InspectionStore(),
                model=FakeModel(0.1),
                policies={"bottle": DecisionPolicy("policy-1", frozenset({"efficientad-s-native-v1"}), 0.2, 0.8)},
                image_root=directory,
            )
            try:
                record = api.handle(
                    "POST", "/api/v1/inspections", json.dumps({"category": "bottle", "image_path": "sample.png"}).encode(),
                    {"Idempotency-Key": "missing-heatmap"},
                )[1]
                self.assertEqual(record["outcome"], "PASS")
                self.assertEqual(record["evidence"], {})
            finally:
                api.store.close()

    def test_heatmap_evidence_survives_read_back(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "sample.png"
            image.write_bytes(b"image-placeholder")
            class HeatmapModel(FakeModel):
                def score(self, _category: str, _image: str | Path) -> FakeEvidence:
                    return FakeEvidence(0.1, [[0.0, 1.0], [0.5, 0.25]])
            api = InspectionApi(
                InspectionStore(), model=HeatmapModel(0.1),
                policies={"bottle": DecisionPolicy("policy-1", frozenset({"efficientad-s-native-v1"}), 0.2, 0.8)},
                image_root=directory,
            )
            try:
                record = api.handle("POST", "/api/v1/inspections", json.dumps({"category": "bottle", "image_path": "sample.png"}).encode(), {"Idempotency-Key": "heatmap"})[1]
                self.assertTrue(record["evidence"]["heatmap_url"].startswith("data:image/png;base64,"))
                loaded = api.handle("GET", f"/api/v1/inspections/{record['inspection_id']}")[1]
                self.assertEqual(loaded["evidence"], record["evidence"])
            finally:
                api.store.close()

    def test_reload_model_delegates_to_configured_runtime(self) -> None:
        api = InspectionApi(InspectionStore(), model=FakeModel(0.1))
        try:
            self.assertEqual(api.reload_model("bottle"), [])
        finally:
            api.store.close()

    def test_phone_camera_configure_capture_persists_decision_and_input_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            now = datetime.now(timezone.utc)
            frame = type("Frame", (), {"frame": np.zeros((64, 64, 3), dtype=np.uint8), "captured_at_utc": now.isoformat(), "camera_id": "fake", "sequence_no": 1, "width": 64, "height": 64})()
            source = FakeCamera(frame)
            api = InspectionApi(InspectionStore(), model=FakeModel(0.1), policies={"bottle": DecisionPolicy("policy-1", frozenset({"efficientad-s-native-v1"}), 0.2, 0.8)}, image_root=directory, camera_source_factory=lambda _url: source)
            try:
                status, configured = api.handle("POST", "/api/v1/camera/configure", json.dumps({"url": "http://127.0.0.1:8080/video"}).encode())
                self.assertEqual(status, 200)
                self.assertEqual(configured["url"], "http://127.0.0.1:8080/video")
                status, record = api.handle("POST", "/api/v1/camera/capture-inspection", json.dumps({"category": "bottle"}).encode(), {"Idempotency-Key": "camera-one"})
                self.assertEqual(status, 200)
                self.assertEqual(record["outcome"], "PASS")
                self.assertTrue(record["evidence"]["input_image_data"].startswith("data:image/png;base64,"))
                events = api.handle("GET", f"/api/v1/inspections/{record['inspection_id']}/events")[1]["items"]
                self.assertEqual([event["event_type"] for event in events], ["inspection.created", "inspection.decision_recorded"])
                duplicate = api.handle("POST", "/api/v1/camera/capture-inspection", json.dumps({"category": "bottle"}).encode(), {"Idempotency-Key": "camera-one"})[1]
                self.assertEqual(duplicate["inspection_id"], record["inspection_id"])
            finally:
                api.store.close()

    def test_phone_camera_failure_is_unverified_and_does_not_leak_url(self) -> None:
        api = InspectionApi(InspectionStore(), camera_source_factory=lambda _url: FakeCamera(error="offline"))
        try:
            with self.assertRaisesRegex(Exception, "credential-like"):
                api.handle("POST", "/api/v1/camera/configure", json.dumps({"url": "http://127.0.0.1:8080/video?token=secret"}).encode())
            with self.assertRaisesRegex(Exception, "could not be opened"):
                api.handle("POST", "/api/v1/camera/configure", json.dumps({"url": "http://127.0.0.1:8080/video"}).encode())
            self.assertNotIn("secret", json.dumps(api.handle("GET", "/api/v1/camera/status")[1]))
        finally:
            api.store.close()


if __name__ == "__main__":
    unittest.main()
