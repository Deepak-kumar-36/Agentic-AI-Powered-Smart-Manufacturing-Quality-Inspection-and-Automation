import tempfile
import unittest
from pathlib import Path

from app.persistence import InspectionStore


class InspectionStoreTests(unittest.TestCase):
    def test_create_decide_read_back_after_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "inspection.db"
            store = InspectionStore(path)
            record = store.create("request-1", {"category": "bottle", "image_sha256": "abc"})
            store.record_decision(
                record.inspection_id,
                outcome="UNVERIFIED",
                reason_codes=["MODEL_NOT_READY"],
                policy_version="policy-unverified",
                model_version=None,
                score=None,
            )
            store.close()
            reopened = InspectionStore(path)
            loaded = reopened.get(record.inspection_id)
            self.assertEqual(loaded.outcome, "UNVERIFIED")
            self.assertEqual(loaded.reason_codes, ("MODEL_NOT_READY",))
            self.assertEqual(len(reopened.events(record.inspection_id)), 2)
            reopened.close()

    def test_same_idempotency_key_returns_same_record(self) -> None:
        store = InspectionStore()
        first = store.create("same", {"category": "bottle"})
        second = store.create("same", {"category": "bottle"})
        self.assertEqual(first.inspection_id, second.inspection_id)
        with self.assertRaises(ValueError):
            store.create("same", {"category": "cable"})
        store.close()

    def test_reviews_are_additive_and_survive_reopen_without_changing_decision(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "inspection.db"
            store = InspectionStore(path)
            record = store.create("review-request", {"category": "bottle", "image_sha256": "abc123"})
            store.record_decision(record.inspection_id, outcome="PASS", reason_codes=["WITHIN_THRESHOLD"], policy_version="policy-1", model_version="model-1", score=0.1, evidence={"heatmap_url": "data:image/png;base64,x"})
            first = store.add_review(record.inspection_id, outcome="CONFIRMED_NORMAL", note="Looks good")
            second = store.add_review(record.inspection_id, outcome="INCONCLUSIVE", note="Needs another angle")
            self.assertEqual([item.outcome for item in store.reviews(record.inspection_id)], ["CONFIRMED_NORMAL", "INCONCLUSIVE"])
            self.assertNotEqual(first.review_id, second.review_id)
            self.assertEqual(store.get(record.inspection_id).score, 0.1)
            store.close()
            reopened = InspectionStore(path)
            self.assertEqual(len(reopened.reviews(record.inspection_id)), 2)
            self.assertEqual(reopened.reviews(record.inspection_id)[0].input_image_hash, "abc123")
            self.assertTrue(any(event["event_type"] == "inspection.review_recorded" for event in reopened.events(record.inspection_id)))
            reopened.close()


if __name__ == "__main__":
    unittest.main()
