import json
import base64
import hashlib
from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timezone
import numpy as np

from app.api import InspectionApi
from app.persistence import InspectionStore
from app.policy import DecisionPolicy
from app.hardware import HardwareSnapshot


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


class FakeHardware:
    def __init__(self):
        self.decisions = []
        self.closed = False

    def send_decision(self, inspection_id, decision):
        self.decisions.append((inspection_id, decision))

    def snapshot(self):
        return HardwareSnapshot(True, "connected", None, "cmd-1", "acknowledged", "PASS", "green", False, 1.0, "test")

    def close(self):
        self.closed = True


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

    def test_hardware_is_disabled_by_default_and_receives_final_server_decision(self) -> None:
        status, disabled = self.api.handle("GET", "/api/v1/hardware/status")
        self.assertEqual(status, 200)
        self.assertEqual(disabled["state"], "disabled")
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "sample.png"
            from PIL import Image
            Image.new("RGB", (2, 2), (1, 2, 3)).save(image)
            hardware = FakeHardware()
            api = InspectionApi(InspectionStore(), model=FakeModel(0.1), policies={"bottle": DecisionPolicy("p", frozenset({"efficientad-s-native-v1"}), 0.2, 0.8)}, image_root=directory, hardware=hardware)
            try:
                _, record = api.handle("POST", "/api/v1/inspections", json.dumps({"category": "bottle", "image_path": "sample.png", "outcome": "FAIL", "score": 99}).encode(), {"Idempotency-Key": "hardware-decision"})
                self.assertEqual(record["outcome"], "PASS")
                self.assertEqual(hardware.decisions, [(record["inspection_id"], "PASS")])
                self.assertEqual(api.handle("GET", "/api/v1/hardware/status")[1]["last_command_state"], "acknowledged")
            finally:
                api.hardware.close()
                api.store.close()

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
            image.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\xc9\xfe\x92\xef\x00\x00\x00\x00IEND\xaeB`\x82")
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
            image.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\xc9\xfe\x92\xef\x00\x00\x00\x00IEND\xaeB`\x82")
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
                self.assertEqual(record["evidence"]["input_image_bytes"], 69)
                self.assertNotIn("heatmap_url", record["evidence"])
            finally:
                api.store.close()

    def test_heatmap_evidence_survives_read_back(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "sample.png"
            image.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\xc9\xfe\x92\xef\x00\x00\x00\x00IEND\xaeB`\x82")
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

    def test_direct_image_records_hash_from_actual_bytes_and_validates_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "sample.png"
            raw = image.read_bytes() if image.exists() else b""
            raw = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\xc9\xfe\x92\xef\x00\x00\x00\x00IEND\xaeB`\x82"
            image.write_bytes(raw)
            api = InspectionApi(InspectionStore(), image_root=directory)
            try:
                record = api.handle("POST", "/api/v1/inspections", json.dumps({"category": "bottle", "image_path": "sample.png"}).encode(), {"Idempotency-Key": "direct-hash"})[1]
                self.assertEqual(record["evidence"]["input_image_sha256"], hashlib.sha256(raw).hexdigest())
                created = api.handle("GET", f"/api/v1/inspections/{record['inspection_id']}/events")[1]["items"][0]["payload"]
                self.assertEqual(created["image_sha256"], record["evidence"]["input_image_sha256"])
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
                stored = next(Path(directory).glob("phone-camera-*.png"))
                self.assertEqual(record["evidence"]["input_image_sha256"], hashlib.sha256(stored.read_bytes()).hexdigest())
                events = api.handle("GET", f"/api/v1/inspections/{record['inspection_id']}/events")[1]["items"]
                self.assertEqual([event["event_type"] for event in events], ["inspection.created", "inspection.decision_recorded"])
                duplicate = api.handle("POST", "/api/v1/camera/capture-inspection", json.dumps({"category": "bottle"}).encode(), {"Idempotency-Key": "camera-one"})[1]
                self.assertEqual(duplicate["inspection_id"], record["inspection_id"])
            finally:
                api.store.close()

    def test_phone_camera_preserves_input_evidence_when_model_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            now = datetime.now(timezone.utc)
            frame = type("Frame", (), {"frame": np.zeros((64, 64, 3), dtype=np.uint8), "captured_at_utc": now.isoformat(), "camera_id": "fake", "sequence_no": 1, "width": 64, "height": 64})()
            source = FakeCamera(frame)
            api = InspectionApi(InspectionStore(), image_root=directory, camera_source_factory=lambda _url: source)
            try:
                api.handle("POST", "/api/v1/camera/configure", json.dumps({"url": "http://127.0.0.1:8080/video"}).encode())
                status, record = api.handle("POST", "/api/v1/camera/capture-inspection", json.dumps({"category": "bottle"}).encode(), {"Idempotency-Key": "camera-unavailable"})
                self.assertEqual(status, 200)
                self.assertEqual(record["reason_codes"], ["MODEL_NOT_READY"])
                stored = next(Path(directory).glob("phone-camera-*.png"))
                self.assertEqual(record["evidence"]["input_image_bytes"], stored.stat().st_size)
                self.assertEqual(record["evidence"]["input_image_sha256"], hashlib.sha256(stored.read_bytes()).hexdigest())
                self.assertEqual(record["evidence"]["image_path"], stored.name)
            finally:
                api.store.close()

    def test_phone_camera_storage_failure_is_explicit_and_has_no_verified_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            now = datetime.now(timezone.utc)
            frame = type("Frame", (), {"frame": np.zeros((64, 64, 3), dtype=np.uint8), "captured_at_utc": now.isoformat(), "camera_id": "fake", "sequence_no": 1, "width": 64, "height": 64})()
            source = FakeCamera(frame)
            api = InspectionApi(InspectionStore(), image_root=directory, camera_source_factory=lambda _url: source)
            api._atomic_store = lambda *_args: (_ for _ in ()).throw(OSError("disk full"))
            try:
                api.handle("POST", "/api/v1/camera/configure", json.dumps({"url": "http://127.0.0.1:8080/video"}).encode())
                status, record = api.handle("POST", "/api/v1/camera/capture-inspection", json.dumps({"category": "bottle"}).encode(), {"Idempotency-Key": "camera-storage-failure"})
                self.assertEqual(status, 200)
                self.assertEqual(record["outcome"], "UNVERIFIED")
                self.assertEqual(record["reason_codes"], ["EVIDENCE_STORAGE_FAILED"])
                self.assertEqual(record["evidence"], {})
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

    def test_review_routes_validate_and_preserve_ai_record(self) -> None:
        record = self.api.handle("POST", "/api/v1/inspections", json.dumps({"category": "bottle"}).encode(), {"Idempotency-Key": "review-api"})[1]
        review_status, review = self.api.handle("POST", f"/api/v1/inspections/{record['inspection_id']}/reviews", json.dumps({"outcome": "CONFIRMED_DEFECT", "defect_type": "scratch", "note": "Visible mark"}).encode())
        self.assertEqual(review_status, 201)
        self.assertEqual(review["model_version"], None)
        self.assertEqual(review["defect_type"], "scratch")
        history = self.api.handle("GET", f"/api/v1/inspections/{record['inspection_id']}/reviews")[1]["items"]
        self.assertEqual(len(history), 1)
        original = self.api.handle("GET", f"/api/v1/inspections/{record['inspection_id']}")[1]
        self.assertEqual(original["outcome"], "UNVERIFIED")
        with self.assertRaisesRegex(Exception, "defect_type is only supported"):
            self.api.handle("POST", f"/api/v1/inspections/{record['inspection_id']}/reviews", json.dumps({"outcome": "CONFIRMED_NORMAL", "defect_type": "scratch"}).encode())
        with self.assertRaisesRegex(Exception, "note must be text"):
            self.api.handle("POST", f"/api/v1/inspections/{record['inspection_id']}/reviews", json.dumps({"outcome": "INCONCLUSIVE", "note": "x" * 2001}).encode())

    def test_review_rejects_unknown_inspection_and_invalid_outcome(self) -> None:
        with self.assertRaises(Exception):
            self.api.handle("POST", "/api/v1/inspections/ins_missing/reviews", b'{"outcome":"INCONCLUSIVE"}')
        record = self.api.handle("POST", "/api/v1/inspections", json.dumps({"category": "bottle"}).encode(), {"Idempotency-Key": "review-invalid"})[1]
        with self.assertRaisesRegex(Exception, "outcome must be"):
            self.api.handle("POST", f"/api/v1/inspections/{record['inspection_id']}/reviews", b'{"outcome":"PASS"}')

    def test_review_analytics_route_supports_filters_and_rejects_invalid_pagination(self) -> None:
        record = self.api.handle("POST", "/api/v1/inspections", json.dumps({"category": "bottle"}).encode(), {"Idempotency-Key": "analytics-api"})[1]
        self.api.handle("POST", f"/api/v1/inspections/{record['inspection_id']}/reviews", b'{"outcome":"INCONCLUSIVE"}')
        status, payload = self.api.handle("GET", "/api/v1/review-analytics?review_state=INCONCLUSIVE&page=1&page_size=1")
        self.assertEqual(status, 200)
        self.assertEqual(payload["total_inspections"], 1)
        self.assertEqual(payload["items"][0]["latest_review_outcome"], "INCONCLUSIVE")
        with self.assertRaisesRegex(Exception, "page_size"):
            self.api.handle("GET", "/api/v1/review-analytics?page_size=101")


if __name__ == "__main__":
    unittest.main()
