import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from app.efficientad.release import EfficientADReleaseError, load_reviewed_release


class EfficientADReleaseTests(unittest.TestCase):
    def _metadata(self, root: Path, *, status: str = "QUALIFIED", mode: str = "full") -> tuple[Path, Path]:
        teacher = root / "teacher.pth"
        teacher.write_bytes(b"teacher")
        checkpoint = root / "reference_teacher" / "bottle" / "efficientad_s_bottle.pt"
        checkpoint.parent.mkdir(parents=True)
        checkpoint.write_bytes(b"checkpoint")
        digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        metadata = {
            "run_mode": mode,
            "qualification_status": status,
            "implementation": "native",
            "categories": ["bottle"],
            "teacher_sha256": digest(teacher),
            "training_summary": [{"category": "bottle", "checkpoint_sha256": digest(checkpoint)}],
        }
        metadata_path = root / "run_metadata.json"
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
        return metadata_path, teacher

    def test_smoke_run_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata, teacher = self._metadata(root, mode="smoke")
            with self.assertRaisesRegex(EfficientADReleaseError, "full Kaggle"):
                load_reviewed_release(metadata, root, teacher, {"bottle": (0.2, 0.8)})

    def test_unqualified_run_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata, teacher = self._metadata(root)
            metadata.write_text(metadata.read_text(encoding="utf-8").replace("QUALIFIED", "NOT_QUALIFIED"), encoding="utf-8")
            with self.assertRaisesRegex(EfficientADReleaseError, "not explicitly qualified"):
                load_reviewed_release(metadata, root, teacher, {"bottle": (0.2, 0.8)})

    def test_reviewed_release_validates_hashes_and_policies(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata, teacher = self._metadata(root)
            release = load_reviewed_release(metadata, root, teacher, {"bottle": (0.2, 0.8)})
            self.assertEqual(release.checkpoints["bottle"].name, "efficientad_s_bottle.pt")
            self.assertEqual(release.policies["bottle"].fail_threshold, 0.8)

    def test_metadata_contract_contains_release_facts_without_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata, teacher = self._metadata(root)
            release = load_reviewed_release(metadata, root, teacher, {"bottle": (0.2, 0.8)})
            contract = release.metadata_contract()
            self.assertEqual(contract["categories"], ["bottle"])
            self.assertEqual(contract["model_versions"], ["efficientad-s-native-v1"])
            self.assertEqual(contract["policies"][0]["fail_threshold"], 0.8)
            self.assertEqual(contract["qualification"]["status"], "QUALIFIED")
            self.assertEqual(contract["training_summary"][0]["category"], "bottle")
            self.assertNotIn("teacher_path", json.dumps(contract))
            self.assertNotIn(str(root), json.dumps(contract))

    def test_supervised_local_qualification_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            metadata, teacher = self._metadata(root)
            text = metadata.read_text(encoding="utf-8").replace("QUALIFIED", "QUALIFIED_FOR_SUPERVISED_LOCAL_API")
            metadata.write_text(text, encoding="utf-8")
            release = load_reviewed_release(metadata, root, teacher, {"bottle": (0.2, 0.8)})
            self.assertEqual(release.metadata["qualification_status"], "QUALIFIED_FOR_SUPERVISED_LOCAL_API")


if __name__ == "__main__":
    unittest.main()
