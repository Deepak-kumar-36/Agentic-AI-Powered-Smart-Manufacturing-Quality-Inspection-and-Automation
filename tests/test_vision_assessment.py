import io
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from app.api import ApiError, InspectionApi
from app.persistence import InspectionStore
from app.vision_assessment import VisionAssessmentService, VisionError, validate_assessment
from tests.test_api import FakeHardware


class FakeVision:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, 0

    def assess(self, image, mime_type):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


def png():
    data = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(data, format="PNG")
    return data.getvalue()


class VisionAssessmentTests(unittest.TestCase):
    def test_provider_disabled_and_missing_key(self):
        with self.assertRaisesRegex(VisionError, "disabled"):
            VisionAssessmentService(enabled=False, provider=FakeVision()).assess("i", png(), "image/png")
        with self.assertRaisesRegex(VisionError, "GEMINI_API_KEY"):
            VisionAssessmentService(enabled=True, api_key="", provider=None).assess("i", png(), "image/png")

    def test_valid_assessment_categories_and_unsupported_category(self):
        for value in ("LIKELY_NORMAL", "POSSIBLE_DEFECT", "INCONCLUSIVE"):
            result = validate_assessment({"assessment": value, "defect_type": "unknown", "observations": [], "limitations": []}, "model-id")
            self.assertFalse(result["qualified"])
            self.assertEqual(result["evaluation_mode"], "DEMO_ADVISORY")
        with self.assertRaises(VisionError):
            validate_assessment({"assessment": "POSSIBLE_DEFECT", "defect_type": "explosion", "observations": [], "limitations": []}, "model")

    def test_malformed_output_and_provider_failures(self):
        with self.assertRaises(VisionError):
            validate_assessment("not json", "model")
        for error, expected in ((TimeoutError(), "VISION_TIMEOUT"), (RuntimeError("quota"), "VISION_PROVIDER_ERROR")):
            with self.assertRaises(VisionError) as caught:
                VisionAssessmentService(enabled=True, api_key="test", provider=FakeVision(error=error)).assess("i", png(), "image/png")
            self.assertEqual(caught.exception.code, expected)
        class RateError(Exception):
            code = 429
        with self.assertRaises(VisionError) as caught:
            VisionAssessmentService(enabled=True, api_key="test", provider=FakeVision(error=RateError())).assess("i", png(), "image/png")
        self.assertEqual(caught.exception.code, "VISION_RATE_LIMITED")

    def test_invalid_and_oversized_image_rejected(self):
        service = VisionAssessmentService(enabled=True, api_key="test", provider=FakeVision())
        for image in (b"invalid", b"x" * (10 * 1024 * 1024 + 1)):
            with self.assertRaises(VisionError):
                service.assess("i", image, "image/png")

    def test_explicit_endpoint_uses_managed_hash_verified_image_and_preserves_decision(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            raw = png()
            (root / "managed.png").write_bytes(raw)
            store = InspectionStore()
            record = store.create("key", {"category": "part"})
            import hashlib
            store.record_decision(record.inspection_id, outcome="UNVERIFIED", reason_codes=["MODEL_NOT_READY"], policy_version="p", model_version=None, score=None, evidence={"image_path": "managed.png", "input_image_sha256": hashlib.sha256(raw).hexdigest()})
            fake = FakeVision({"assessment": "POSSIBLE_DEFECT", "defect_type": "scratch", "observations": ["Visible line"], "limitations": ["Low resolution"]})
            hardware = FakeHardware()
            api = InspectionApi(store, image_root=root, hardware=hardware, vision_assessment=VisionAssessmentService(enabled=True, api_key="test", model="flash-test", provider=fake))
            before = store.get(record.inspection_id)
            event_count = len(store.events(record.inspection_id))
            status, result = api.handle("POST", f"/api/v1/inspections/{record.inspection_id}/vision-assessment", b"{}")
            self.assertEqual(status, 200)
            self.assertEqual(result["assessment"], "POSSIBLE_DEFECT")
            self.assertFalse(result["qualified"])
            self.assertEqual(store.get(record.inspection_id), before)
            self.assertEqual(len(store.events(record.inspection_id)), event_count)
            self.assertEqual(store.reviews(record.inspection_id), [])
            self.assertEqual(hardware.decisions, [])
            self.assertEqual(fake.calls, 1)
            store.close()

    def test_bad_or_arbitrary_reference_rejected_and_disabled_endpoint_has_clear_error(self):
        store = InspectionStore()
        record = store.create("key2", {"category": "part"})
        store.record_decision(record.inspection_id, outcome="UNVERIFIED", reason_codes=["IMAGE_INVALID"], policy_version="p", model_version=None, score=None, evidence={"image_path": "/etc/passwd"})
        api = InspectionApi(store, image_root="/tmp/vision-empty")
        with self.assertRaises(ApiError) as caught:
            api.handle("POST", f"/api/v1/inspections/{record.inspection_id}/vision-assessment", b"{}")
        self.assertEqual(caught.exception.status, 422)
        with self.assertRaises(ApiError) as caught:
            api.handle("POST", "/api/v1/inspections/no-such-id/vision-assessment", b"{}")
        self.assertEqual(caught.exception.status, 404)
        store.close()


if __name__ == "__main__":
    unittest.main()
