import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from PIL import Image

from app.api import InspectionApi
from app.dataset_intake import stage_package
from app.dataset_package import validate_package
from app.persistence import InspectionStore
from app.policy import DecisionPolicy
from app.review_export import build


class _Evidence:
    model_version = "test-model"
    score = 0.1
    heatmap = None


class _Model:
    def score(self, _category, _image):
        return _Evidence()


class EvidenceWorkflowTests(unittest.TestCase):
    def test_inspect_review_export_validate_and_stage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw_buffer = io.BytesIO()
            Image.new("RGB", (8, 6), (30, 60, 90)).save(raw_buffer, format="PNG")
            raw = raw_buffer.getvalue()
            image = root / "input.png"
            image.write_bytes(raw)
            store = InspectionStore(root / "inspection.sqlite3")
            self.addCleanup(store.close)
            api = InspectionApi(store, model=_Model(), policies={"bottle": DecisionPolicy("p", frozenset({"test-model"}), 0.2, 0.8)}, image_root=root)

            status, record = api.handle("POST", "/api/v1/inspections", json.dumps({"category": "bottle", "image_path": "input.png"}).encode(), {"Idempotency-Key": "e2e-image"})
            self.assertEqual(status, 201)
            digest = hashlib.sha256(raw).hexdigest()
            self.assertEqual(record["evidence"]["input_image_sha256"], digest)
            self.assertEqual(Path(record["evidence"]["image_path"]), Path("input.png"))
            self.assertEqual(api.handle("GET", f"/api/v1/inspections/{record['inspection_id']}")[1]["evidence"]["input_image_sha256"], digest)

            status, review = api.handle("POST", f"/api/v1/inspections/{record['inspection_id']}/reviews", b'{"outcome":"CONFIRMED_NORMAL"}')
            self.assertEqual(status, 201)
            self.assertEqual(review["input_image_hash"], digest)

            result = build(store, image_root=root)
            self.assertEqual(result.summary["included_count"], 1)
            package = root / "reviewed.zip"
            package.write_bytes(result.archive)
            report = validate_package(package)
            self.assertIn(report["status"], {"VALID", "VALID_WITH_WARNINGS"})
            self.assertEqual(report["counts"]["records"], 1)
            staging = root / "staging"
            staged = stage_package(package, staging)
            self.assertIsNotNone(staged["destination"])
            candidate = staging / staged["destination"]
            row = json.loads((candidate / "manifest.jsonl").read_text().strip())
            self.assertEqual(row["input_image_sha256"], digest)
            self.assertFalse(json.loads((candidate / "staging-manifest.json").read_text())["training_approved"])


if __name__ == "__main__":
    unittest.main()
