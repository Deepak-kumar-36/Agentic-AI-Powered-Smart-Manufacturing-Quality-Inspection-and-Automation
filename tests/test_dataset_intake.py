import base64
from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from PIL import Image

from app.dataset_intake import stage_package
from app.dataset_package import PackageLimits, validate_package
from app.persistence import InspectionStore
from app.review_export import build


class DatasetIntakeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.package = self.root / "private-original-name.zip"
        self.staging = self.root / "staging"
        store = InspectionStore()
        self.addCleanup(store.close)
        for index, outcome in enumerate(("CONFIRMED_NORMAL", "CONFIRMED_DEFECT")):
            output = io.BytesIO()
            Image.new("RGB", (4, 3), (index * 100, 40, 60)).save(output, format="PNG")
            raw = output.getvalue()
            record = store.create(str(index), {"category": "bottle", "image_sha256": hashlib.sha256(raw).hexdigest()})
            store.record_decision(record.inspection_id, outcome="UNVERIFIED", reason_codes=[], policy_version="p", model_version="m", score=0.2,
                                  evidence={"input_image_data": "data:image/png;base64," + base64.b64encode(raw).decode()})
            store.add_review(record.inspection_id, outcome=outcome, defect_type="scratch" if index else None)
        self.package.write_bytes(build(store).archive)

    def cli(self, *arguments):
        return subprocess.run([sys.executable, "-m", "app.dataset_intake", *map(str, arguments)], capture_output=True, text=True)

    def test_exporter_fixture_stages_preserving_human_labels_and_provenance(self):
        before = self.package.read_bytes()
        result = stage_package(self.package, self.staging)
        self.assertIn(result["report"]["status"], {"VALID", "VALID_WITH_WARNINGS"})
        destination = self.staging / result["destination"]
        self.assertRegex(destination.name, r"^candidate-[0-9a-f]{32}$")
        self.assertEqual(destination.stat().st_mode & 0o777, 0o700)
        self.assertEqual({item.name for item in destination.iterdir()}, {"images", "manifest.jsonl", "staging-manifest.json", "validation-report.json"})
        rows = [json.loads(line) for line in (destination / "manifest.jsonl").read_text().splitlines()]
        with zipfile.ZipFile(self.package) as archive:
            originals = [json.loads(line) for line in archive.read("manifest.jsonl").decode().splitlines()]
            for row, original in zip(rows, originals):
                expected = dict(original, image_path=row["image_path"])
                self.assertEqual(row, expected)
                self.assertEqual((destination / row["image_path"]).read_bytes(), archive.read(original["image_path"]))
                self.assertNotIn("split", row)
        metadata = json.loads((destination / "staging-manifest.json").read_text())
        self.assertTrue(metadata["candidate_only"])
        self.assertFalse(metadata["training_approved"])
        self.assertEqual(metadata["source_sha256"], hashlib.sha256(before).hexdigest())
        self.assertEqual([item["source_image_path"] for item in metadata["image_mapping"]], [row["image_path"] for row in originals])
        self.assertEqual(json.loads((destination / "validation-report.json").read_text()), result["report"])
        for name in ("staging-manifest.json", "validation-report.json", "manifest.jsonl"):
            self.assertNotIn(str(self.root), (destination / name).read_text())
            self.assertNotIn(self.package.name, (destination / name).read_text())
        self.assertEqual(self.package.read_bytes(), before)

    def test_invalid_package_creates_no_candidate(self):
        self.package.write_bytes(b"not a zip")
        result = stage_package(self.package, self.staging)
        self.assertIsNone(result["destination"])
        self.assertEqual(result["report"]["status"], "INVALID")
        self.assertFalse(self.staging.exists())

    def test_repeat_is_distinct_and_preserves_existing_candidate(self):
        first = stage_package(self.package, self.staging)
        original = (self.staging / first["destination"] / "manifest.jsonl").read_bytes()
        second = stage_package(self.package, self.staging)
        self.assertNotEqual(first["destination"], second["destination"])
        self.assertEqual((self.staging / first["destination"] / "manifest.jsonl").read_bytes(), original)
        self.assertEqual(len(list(self.staging.iterdir())), 2)

    def test_injected_write_failure_removes_incomplete_directory(self):
        original_open = Path.open

        def failing_open(path, *args, **kwargs):
            if path.name == "staging-manifest.json":
                raise OSError("injected write failure")
            return original_open(path, *args, **kwargs)

        with patch.object(Path, "open", failing_open), self.assertRaises(OSError):
            stage_package(self.package, self.staging)
        self.assertEqual(list(self.staging.iterdir()), [])

    def test_publication_collision_cannot_replace_even_empty_directory(self):
        self.staging.mkdir()
        occupied = self.staging / ("candidate-" + "a" * 32)
        occupied.mkdir()
        with patch("app.dataset_intake.uuid.uuid4") as generated:
            generated.return_value.hex = "a" * 32
            with self.assertRaises(FileExistsError):
                stage_package(self.package, self.staging)
        self.assertEqual(list(self.staging.iterdir()), [occupied])

    def test_symlink_root_is_refused(self):
        outside = self.root / "outside"
        outside.mkdir()
        self.staging.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(OSError):
            stage_package(self.package, self.staging)
        self.assertEqual(list(outside.iterdir()), [])

    def test_source_replacement_after_snapshot_does_not_change_staged_bytes(self):
        original = self.package.read_bytes()

        def validate_and_replace(snapshot, limits):
            report = validate_package(snapshot, limits)
            self.package.write_bytes(b"replacement")
            return report

        with patch("app.dataset_intake.validate_package", side_effect=validate_and_replace):
            result = stage_package(self.package, self.staging)
        self.assertEqual(result["report"]["source_sha256"], hashlib.sha256(original).hexdigest())
        self.assertTrue((self.staging / result["destination"] / "images").is_dir())

    def test_snapshot_digest_mismatch_rejected(self):
        def incorrect_digest(snapshot, limits):
            return dict(validate_package(snapshot, limits), source_sha256="0" * 64)

        with patch("app.dataset_intake.validate_package", side_effect=incorrect_digest), self.assertRaises(ValueError):
            stage_package(self.package, self.staging)
        self.assertFalse(self.staging.exists())

    def test_limits_bound_snapshot_and_members(self):
        for limits in (replace(PackageLimits(), max_compressed_bytes=1), replace(PackageLimits(), max_images=1),
                       replace(PackageLimits(), max_image_bytes=1), replace(PackageLimits(), max_pixels=1)):
            with self.subTest(limits=limits):
                result = stage_package(self.package, self.staging, limits)
                self.assertEqual(result["report"]["status"], "INVALID")
                self.assertIsNone(result["destination"])
        self.assertFalse(self.staging.exists())

    def test_cli_validate_deterministic_json_and_exclusive_report(self):
        report_path = self.root / "report.json"
        first = self.cli("validate", self.package, "--report", report_path)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(first.stdout, report_path.read_text())
        self.assertEqual(first.stdout, self.cli("validate", self.package).stdout)
        self.assertEqual(first.stdout, json.dumps(json.loads(first.stdout), sort_keys=True, indent=2) + "\n")
        second = self.cli("stage", self.package, "--staging-root", self.staging, "--report", report_path)
        self.assertEqual(second.returncode, 2)
        self.assertEqual(first.stdout, report_path.read_text())
        self.assertFalse(self.staging.exists())

    def test_cli_stage_and_limits_and_exit_codes(self):
        staged = self.cli("stage", self.package, "--staging-root", self.staging)
        self.assertEqual(staged.returncode, 0, staged.stderr)
        self.assertTrue((self.staging / json.loads(staged.stdout)["destination"]).is_dir())
        for flag in ("--max-compressed-bytes", "--max-uncompressed-bytes", "--max-images", "--max-image-bytes", "--max-metadata-bytes", "--max-compression-ratio", "--max-pixels"):
            limited = self.cli("validate", self.package, flag, "1")
            self.assertEqual(limited.returncode, 1, (flag, limited.stderr))
            self.assertEqual(json.loads(limited.stdout)["status"], "INVALID")
        self.assertEqual(self.cli("validate", self.package, "--max-images", "0").returncode, 2)
        self.assertEqual(self.cli("validate", self.package, "--max-compression-ratio", "nan").returncode, 2)
        self.assertEqual(self.cli("stage", self.package).returncode, 2)
        missing = self.cli("validate", self.root / "private-missing.zip")
        self.assertEqual(missing.returncode, 2)
        self.assertNotIn(str(self.root), missing.stdout + missing.stderr)
        self.package.write_bytes(b"broken")
        invalid = self.cli("validate", self.package)
        self.assertEqual(invalid.returncode, 1)
        self.assertEqual(json.loads(invalid.stdout)["status"], "INVALID")


if __name__ == "__main__":
    unittest.main()
