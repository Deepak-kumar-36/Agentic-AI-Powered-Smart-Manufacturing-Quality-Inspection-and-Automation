import json
import unittest

from app.api import InspectionApi
from app.persistence import InspectionStore


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


if __name__ == "__main__":
    unittest.main()
