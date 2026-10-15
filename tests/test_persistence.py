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


if __name__ == "__main__":
    unittest.main()
