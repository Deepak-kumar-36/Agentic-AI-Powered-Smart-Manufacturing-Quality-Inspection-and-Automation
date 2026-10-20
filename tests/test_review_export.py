import base64
import csv
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from PIL import Image

from app.api import InspectionApi
from app.persistence import InspectionStore
from app.review_export import collect, build


def png_bytes(color=(20, 40, 60)):
    output = io.BytesIO()
    Image.new("RGB", (4, 3), color).save(output, format="PNG")
    return output.getvalue()


class ReviewExportTests(unittest.TestCase):
    def setUp(self):
        self.store = InspectionStore()
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def add(self, key, raw, *, ai="PASS", review="CONFIRMED_NORMAL", hash_value=None, image_path=None, extra_reviews=()):
        payload = {"category": "bottle", "image_sha256": hash_value or hashlib.sha256(raw).hexdigest(), "note": "private"}
        if image_path:
            payload["image_path"] = image_path
        record = self.store.create(key, payload)
        self.store.record_decision(record.inspection_id, outcome=ai, reason_codes=[], policy_version="p", model_version="m", score=0.2, evidence={"input_image_data": "data:image/png;base64," + base64.b64encode(raw).decode(), "private_path": "/secret/file.png"})
        self.store.add_review(record.inspection_id, outcome=review, defect_type="scratch" if review == "CONFIRMED_DEFECT" else None, note="do not export")
        for outcome in extra_reviews:
            self.store.add_review(record.inspection_id, outcome=outcome)
        return record.inspection_id

    def test_eligible_labels_and_unverified_ai_are_exported(self):
        normal = self.add("normal", png_bytes(), review="CONFIRMED_NORMAL")
        defect = self.add("defect", png_bytes((90, 20, 10)), ai="FAIL", review="CONFIRMED_DEFECT")
        unverified = self.add("unverified", png_bytes((1, 2, 3)), ai="UNVERIFIED", review="CONFIRMED_DEFECT")
        included, exclusions, images = collect(self.store, image_root=self.root)
        self.assertEqual({item["inspection_id"] for item in included}, {normal, defect, unverified})
        self.assertEqual(exclusions, [])
        self.assertEqual(len(images), 3)
        self.assertEqual(next(item for item in included if item["inspection_id"] == unverified)["ai_decision"], "UNVERIFIED")

    def test_definitive_eligibility_exclusions_have_reasons(self):
        self.add("inconclusive", png_bytes(), review="INCONCLUSIVE")
        unreviewed = self.store.create("unreviewed", {"category": "bottle"})
        self.store.record_decision(unreviewed.inspection_id, outcome="PASS", reason_codes=[], policy_version="p", model_version="m", score=0.1)
        self.add("conflict", png_bytes((2, 3, 4)), extra_reviews=("CONFIRMED_DEFECT",))
        self.add("mismatch", png_bytes(), hash_value="0" * 64)
        self.add("corrupt", b"not-an-image", hash_value=hashlib.sha256(b"not-an-image").hexdigest())
        included, exclusions, _ = collect(self.store, image_root=self.root)
        self.assertEqual(included, [])
        reasons = {item["reason"] for item in exclusions}
        self.assertTrue({"LATEST_REVIEW_NOT_DEFINITIVE", "NO_HUMAN_REVIEW", "CONFLICTING_REVIEWS", "IMAGE_HASH_MISMATCH", "INVALID_IMAGE"} <= reasons)

    def test_duplicate_hash_and_zip_manifest_redaction_and_integrity(self):
        first = png_bytes()
        first_id = self.add("first", first)
        self.add("duplicate", first)
        before = self.store.get(first_id)
        before_reviews = self.store.reviews(first_id)
        before_events = self.store.events(first_id)
        result = build(self.store, image_root=self.root)
        self.assertEqual(self.store.get(first_id), before)
        self.assertEqual(self.store.reviews(first_id), before_reviews)
        self.assertEqual(self.store.events(first_id), before_events)
        with zipfile.ZipFile(io.BytesIO(result.archive)) as archive:
            names = set(archive.namelist())
            self.assertIn("manifest.jsonl", names)
            self.assertIn("README.md", names)
            self.assertIn("exclusions.csv", names)
            rows = [json.loads(line) for line in archive.read("manifest.jsonl").decode().splitlines()]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["label"], "normal")
            self.assertNotIn("private", archive.read("manifest.jsonl").decode())
            self.assertNotIn("private_path", archive.read("manifest.jsonl").decode())
            exclusions = list(csv.DictReader(io.StringIO(archive.read("exclusions.csv").decode())))
            self.assertEqual(exclusions[0]["reason"], "DUPLICATE_IMAGE_HASH")
            self.assertIn("not approved training data", archive.read("README.md").decode())

    def test_limits_and_api_preview_download(self):
        self.add("bounded", png_bytes())
        _, byte_exclusions, _ = collect(self.store, byte_limit=1)
        self.assertEqual(byte_exclusions[0]["reason"], "BYTE_LIMIT_EXCEEDED")
        with self.assertRaises(ValueError):
            collect(self.store, limit=0)
        with self.assertRaises(ValueError):
            collect(self.store, byte_limit=0)
        api = InspectionApi(self.store, image_root=self.root)
        status, preview = api.handle("GET", "/api/v1/review-export/preview?review_outcome=CONFIRMED_NORMAL")
        self.assertEqual(status, 200)
        self.assertEqual(preview["summary"]["included_count"], 1)
        archive, filename, summary = api.export_download("/api/v1/review-export/download?review_outcome=CONFIRMED_NORMAL")
        self.assertTrue(filename.endswith(".zip"))
        self.assertEqual(summary["included_count"], 1)
        self.assertTrue(zipfile.is_zipfile(io.BytesIO(archive)))
        with self.assertRaises(Exception):
            api.handle("GET", "/api/v1/review-export/preview?limit=101")

    def test_unsafe_path_is_redacted_as_an_exclusion(self):
        raw = png_bytes()
        self.add("unsafe", raw, image_path="../outside.png")
        record = self.store.get(self.store.list()[0].inspection_id)
        # Remove inline evidence so the exporter must resolve the recorded path.
        self.store.connection.execute("UPDATE inspections SET evidence_json = ? WHERE inspection_id = ?", ("{}", record.inspection_id))
        _, exclusions, _ = collect(self.store, image_root=self.root)
        self.assertEqual(exclusions[0]["reason"], "UNSAFE_EVIDENCE_PATH")
        self.assertNotIn(str(self.root), json.dumps(exclusions))


if __name__ == "__main__":
    unittest.main()
