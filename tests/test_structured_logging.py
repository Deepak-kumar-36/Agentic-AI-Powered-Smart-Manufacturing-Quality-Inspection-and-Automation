"""Tests for structured JSON logging, correlation IDs, and redaction (Document 14 / OPS-001)."""

import json
import urllib.request
import urllib.error
from io import StringIO
from pathlib import Path
import threading
import unittest

from app.api import InspectionApi, create_server
from app.persistence import InspectionStore
from app.policy import DecisionPolicy
from app.structured_logging import (
    BOOT_ID,
    SERVICE_NAME,
    SERVICE_VERSION,
    StructuredLogger,
    capture_logs,
    correlation_context,
    redact_url,
    redact_value,
)


class FakeScorer:
    def __init__(self, score_value: float = 0.2) -> None:
        self.score_value = score_value

    def score(self, category: str, image: str | Path):
        class Evidence:
            score = self.score_value
            model_version = "test-model-v1"
            heatmap = None
        return Evidence()


class StructuredLoggingUnitTests(unittest.TestCase):
    def test_common_fields_are_always_present(self) -> None:
        buffer = StringIO()
        logger = StructuredLogger(stream=buffer)
        record = logger.info("test.event", extra_key="extra_value")

        self.assertEqual(record["service"], SERVICE_NAME)
        self.assertEqual(record["service_version"], SERVICE_VERSION)
        self.assertEqual(record["boot_id"], BOOT_ID)
        self.assertEqual(record["level"], "INFO")
        self.assertEqual(record["event"], "test.event")
        self.assertEqual(record["extra_key"], "extra_value")
        self.assertIn("timestamp", record)

        # Output in stream is valid JSON
        line = buffer.getvalue().strip()
        parsed = json.loads(line)
        self.assertEqual(parsed["event"], "test.event")
        self.assertEqual(parsed["service"], SERVICE_NAME)

    def test_correlation_context_propagation(self) -> None:
        buffer = StringIO()
        logger = StructuredLogger(stream=buffer)

        with correlation_context(request_id="req-123", correlation_id="corr-456", inspection_id="ins-789"):
            record = logger.info("context.event", step="validation")
            self.assertEqual(record["request_id"], "req-123")
            self.assertEqual(record["correlation_id"], "corr-456")
            self.assertEqual(record["inspection_id"], "ins-789")

        # After exiting context, IDs are no longer attached
        after_record = logger.info("after.event")
        self.assertNotIn("request_id", after_record)
        self.assertNotIn("correlation_id", after_record)
        self.assertNotIn("inspection_id", after_record)

    def test_log_level_filtering(self) -> None:
        buffer = StringIO()
        logger = StructuredLogger(stream=buffer)
        logger.set_level("WARNING")

        debug_rec = logger.debug("debug.event")
        info_rec = logger.info("info.event")
        warn_rec = logger.warning("warn.event")

        self.assertEqual(debug_rec, {})
        self.assertEqual(info_rec, {})
        self.assertEqual(warn_rec["event"], "warn.event")
        self.assertEqual(warn_rec["level"], "WARNING")

    def test_redaction_of_sensitive_keys(self) -> None:
        data = {
            "api_key": "secret-12345",
            "password": "super-password",
            "access_token": "token-abc",
            "cookie": "session=xyz",
            "safe_field": "visible",
            "nested": {
                "credential": "private-cert",
                "secret_key": "very-secret",
                "ok": 42,
            },
        }
        redacted = redact_value(None, data)
        self.assertEqual(redacted["api_key"], "[REDACTED]")
        self.assertEqual(redacted["password"], "[REDACTED]")
        self.assertEqual(redacted["access_token"], "[REDACTED]")
        self.assertEqual(redacted["cookie"], "[REDACTED]")
        self.assertEqual(redacted["safe_field"], "visible")
        self.assertEqual(redacted["nested"]["credential"], "[REDACTED]")
        self.assertEqual(redacted["nested"]["secret_key"], "[REDACTED]")
        self.assertEqual(redacted["nested"]["ok"], 42)

    def test_redaction_of_image_data_and_raw_bytes(self) -> None:
        payload = {
            "data_base64": "iVBORw0KGgoAAAANSUhEUgAA...",
            "input_image_data": "data:image/png;base64,iVBORw0KGgo...",
            "raw_bytes": b"\x89PNG\r\n\x1a\n\x00\x00",
            "image_bytes": b"fake-png-content",
        }
        redacted = redact_value(None, payload)
        self.assertTrue(redacted["data_base64"].startswith("[REDACTED_IMAGE_DATA"))
        self.assertTrue(redacted["input_image_data"].startswith("[REDACTED_IMAGE_DATA"))
        self.assertTrue(redacted["raw_bytes"].startswith("[REDACTED_BYTES"))
        self.assertTrue(redacted["image_bytes"].startswith("[REDACTED_IMAGE_DATA"))

    def test_redaction_of_credential_urls(self) -> None:
        url_with_auth = "http://operator:admin123@192.168.1.50:8080/video"
        clean = redact_url(url_with_auth)
        self.assertEqual(clean, "http://***:***@192.168.1.50:8080/video")
        self.assertNotIn("operator", clean)
        self.assertNotIn("admin123", clean)

        redacted_dict = redact_value(None, {"camera_url": url_with_auth})
        self.assertEqual(redacted_dict["camera_url"], "http://***:***@192.168.1.50:8080/video")


import tempfile
from PIL import Image

class ApiStructuredLoggingIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.image_path = Path(self.temp_dir.name) / "sample.png"
        img = Image.new("RGB", (50, 50), color=(200, 200, 200))
        img.save(self.image_path)
        self.store = InspectionStore()
        self.policy = DecisionPolicy(version="bottle-v1", compatible_model_versions=frozenset({"test-model-v1"}), pass_threshold=0.1, fail_threshold=0.5)
        self.api = InspectionApi(
            self.store,
            model=FakeScorer(0.05),
            policies={"bottle": self.policy},
            image_root=self.temp_dir.name,
        )

    def tearDown(self) -> None:
        self.store.close()
        self.temp_dir.cleanup()

    def test_inspection_lifecycle_events_logged(self) -> None:
        headers = {
            "Idempotency-Key": "test-key-lifecycle",
            "X-Request-ID": "req-custom-999",
            "X-Correlation-ID": "corr-custom-888",
        }
        body = json.dumps({"category": "bottle", "image_path": "sample.png"}).encode("utf-8")

        with capture_logs() as logs:
            status, record = self.api.handle("POST", "/api/v1/inspections", body, headers)

        self.assertEqual(status, 201)
        events = [item["event"] for item in logs]
        self.assertIn("inspection.created", events)
        self.assertIn("inspection.inference.completed", events)
        self.assertIn("inspection.decision.created", events)

        create_log = next(item for item in logs if item["event"] == "inspection.created")
        self.assertEqual(create_log["request_id"], "req-custom-999")
        self.assertEqual(create_log["correlation_id"], "corr-custom-888")
        self.assertEqual(create_log["inspection_id"], record["inspection_id"])
        self.assertEqual(create_log["category"], "bottle")

        inf_log = next(item for item in logs if item["event"] == "inspection.inference.completed")
        self.assertEqual(inf_log["category"], "bottle")
        self.assertEqual(inf_log["score"], 0.05)
        self.assertIn("duration_ms", inf_log)

        decision_log = next(item for item in logs if item["event"] == "inspection.decision.created")
        self.assertEqual(decision_log["request_id"], "req-custom-999")
        self.assertEqual(decision_log["inspection_id"], record["inspection_id"])
        self.assertEqual(decision_log["outcome"], "PASS")


    def test_human_review_event_logged(self) -> None:
        _, record = self.api.handle(
            "POST",
            "/api/v1/inspections",
            json.dumps({"category": "bottle"}).encode(),
            {"Idempotency-Key": "for-review"},
        )
        insp_id = record["inspection_id"]

        with capture_logs() as logs:
            status, review = self.api.handle(
                "POST",
                f"/api/v1/inspections/{insp_id}/reviews",
                json.dumps({"outcome": "CONFIRMED_DEFECT", "defect_type": "scratch", "note": "visible surface scratch"}).encode(),
                {"X-Request-ID": "req-review-1", "X-Correlation-ID": "corr-review-1"},
            )

        self.assertEqual(status, 201)
        review_logs = [item for item in logs if item["event"] == "operator.review.created"]
        self.assertEqual(len(review_logs), 1)
        entry = review_logs[0]
        self.assertEqual(entry["inspection_id"], insp_id)
        self.assertEqual(entry["outcome"], "CONFIRMED_DEFECT")
        self.assertEqual(entry["defect_type"], "scratch")
        self.assertEqual(entry["request_id"], "req-review-1")

    def test_camera_configuration_redaction_and_event(self) -> None:
        camera_url = "http://user:secretpass@127.0.0.1:8080/stream"
        payload = json.dumps({"url": camera_url}).encode()

        with capture_logs() as logs:
            try:
                self.api.handle("POST", "/api/v1/camera/configure", payload)
            except Exception:
                pass

        # Check that no log contains secretpass
        for item in logs:
            raw = json.dumps(item)
            self.assertNotIn("secretpass", raw)

    def test_http_server_propagates_request_and_correlation_headers(self) -> None:
        server = create_server(self.api, host="127.0.0.1", port=0)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/health/live",
                headers={
                    "X-Request-ID": "req-wire-12345",
                    "X-Correlation-ID": "corr-wire-67890",
                },
            )
            with capture_logs() as logs:
                with urllib.request.urlopen(req) as resp:
                    resp_headers = resp.headers
                    self.assertEqual(resp.status, 200)

            self.assertEqual(resp_headers.get("X-Request-ID"), "req-wire-12345")
            self.assertEqual(resp_headers.get("X-Correlation-ID"), "corr-wire-67890")

            req_started = next(item for item in logs if item["event"] == "api.request.started")
            self.assertEqual(req_started["request_id"], "req-wire-12345")
            self.assertEqual(req_started["correlation_id"], "corr-wire-67890")

            req_completed = next(item for item in logs if item["event"] == "api.request.completed")
            self.assertEqual(req_completed["request_id"], "req-wire-12345")
            self.assertEqual(req_completed["status"], 200)
            self.assertIn("duration_ms", req_completed)
        finally:
            server.shutdown()
            server.server_close()
