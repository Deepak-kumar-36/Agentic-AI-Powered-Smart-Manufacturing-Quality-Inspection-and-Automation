import base64
from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import stat
import struct
import tempfile
import unittest
from unittest.mock import patch
import warnings
import zipfile

from PIL import Image

from app.dataset_package import PackageLimits, validate_package
from app.persistence import InspectionStore
from app.review_export import _readme, build


def png(color=(20, 40, 60)):
    output = io.BytesIO()
    Image.new("RGB", (4, 3), color).save(output, format="PNG")
    return output.getvalue()


def record(raw=None, **updates):
    row = {"image_path": "images/one.png", "inspection_id": "one", "label": "normal",
           "review_outcome": "CONFIRMED_NORMAL", "input_image_sha256": hashlib.sha256(raw or png()).hexdigest(),
           "review_timestamp": "2026-10-20T12:00:00+00:00", "defect_type": None,
           "ai_decision": "UNVERIFIED", "anomaly_score": 0.2, "model_version": "test-v1",
           "inspection_timestamp": None, "capture_source": "unknown",
           "metadata_availability": {"reviewer_identity": "unavailable"}}
    row.update(updates)
    return row


class DatasetPackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "input.zip"

    def tearDown(self):
        self.temp.cleanup()

    def package(self, rows=None, images=None, exclusions="inspection_id,reason\r\n", overrides=None, extra=(), compression=zipfile.ZIP_DEFLATED):
        rows = [record()] if rows is None else rows
        images = {"images/one.png": png()} if images is None else images
        summary = {"included_count": len(rows), "excluded_count": len(exclusions.splitlines()) - 1,
                   "exclusion_counts": {}, "export_complete": True}
        contents = {"manifest.jsonl": "".join(json.dumps(row) + "\n" for row in rows),
                    "README.md": _readme(summary), "exclusions.csv": exclusions, **images}
        contents.update(overrides or {})
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(self.path, "w", compression) as archive:
                for name, value in [*contents.items(), *extra]:
                    archive.writestr(name, value)
        return validate_package(self.path)

    def codes(self, report, kind="errors"):
        return {item["code"] for item in report[kind]}

    def test_exporter_round_trip_and_snapshot_digest(self):
        store = InspectionStore()
        try:
            raw = png()
            item = store.create("one", {"category": "bottle", "image_sha256": hashlib.sha256(raw).hexdigest()})
            store.record_decision(item.inspection_id, outcome="PASS", reason_codes=[], policy_version="p", model_version="m", score=0.1,
                                  evidence={"input_image_data": "data:image/png;base64," + base64.b64encode(raw).decode()})
            store.add_review(item.inspection_id, outcome="CONFIRMED_NORMAL")
            exported = build(store)
        finally:
            store.close()
        self.path.write_bytes(exported.archive)
        result = validate_package(self.path)
        self.assertEqual(result["status"], "VALID_WITH_WARNINGS")
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["source_sha256"], hashlib.sha256(exported.archive).hexdigest())
        for key, value in {"records": 1, "images": 1, "normal": 1, "defect": 0, "excluded": 0,
                           "archive_members": 4, "valid_images": 1, "invalid_images": 0,
                           "verified_hashes": 1, "mismatched_hashes": 0}.items():
            self.assertEqual(result["counts"][key], value)
        self.assertIn("MISSING_GROUPING", self.codes(result, "warnings"))
        self.assertEqual(result, validate_package(self.path))

    def test_empty_export_is_valid_with_warnings(self):
        result = self.package(rows=[], images={})
        self.assertEqual(result["status"], "VALID_WITH_WARNINGS")
        self.assertEqual(result["counts"]["records"], 0)

    def test_unsafe_and_duplicate_entries_rejected_before_reads(self):
        for name in ("../private.png", "/private.png", "C:/private.png", "images\\private.png", "images/../private.png", "images//private.png", "images/./private.png", "images/NUL.png", "images/one.png", "images/ONE.png", "images/one.png\x00hidden"):
            with self.subTest(name=name):
                self.package(extra=[(name, png())])
                with patch.object(zipfile.ZipFile, "open", side_effect=AssertionError("Must preflight")):
                    # NUL names are truncated by the writer, giving a duplicate.
                    result = validate_package(self.path)
                self.assertEqual(result["status"], "INVALID")

    def test_special_entries_and_unexpected_files(self):
        for mode in (stat.S_IFLNK, stat.S_IFIFO, stat.S_IFCHR, stat.S_IFSOCK):
            info = zipfile.ZipInfo("images/link.png")
            info.create_system = 3
            info.external_attr = (mode | 0o777) << 16
            self.assertIn("SPECIAL_ENTRY", self.codes(self.package(extra=[(info, "target")])))
        self.assertIn("UNEXPECTED_FILE", self.codes(self.package(extra=[("run.py", "secret")])) )
        self.assertIn("MISSING_REQUIRED_FILE", self.codes(self._missing_readme()))

    def _missing_readme(self):
        with zipfile.ZipFile(self.path, "w") as archive:
            archive.writestr("manifest.jsonl", "")
        return validate_package(self.path)

    def test_strict_jsonl(self):
        for value in ('{"label":"normal","label":"defect"}', '[]', 'null', '{"score":NaN}', '{"score":Infinity}', '{"score":1e999}', '\n', '{"nested":{"x":1,"x":2}}'):
            with self.subTest(value=value):
                result = self.package(overrides={"manifest.jsonl": value + "\n"})
                self.assertIn("INVALID_JSONL", self.codes(result))
        result = self.package(overrides={"manifest.jsonl": b"\xff"})
        self.assertIn("INVALID_ENCODING", self.codes(result))

    def test_record_contract_invalid_values_never_crash_or_echo(self):
        cases = [({"label": []}, "INVALID_LABEL"), ({"review_outcome": "INCONCLUSIVE"}, "REVIEW_LABEL_MISMATCH"),
                 ({"label": "defect", "review_outcome": "CONFIRMED_NORMAL"}, "REVIEW_LABEL_MISMATCH"),
                 ({"defect_type": "scratch"}, "INVALID_DEFECT_TYPE"),
                 ({"label": "defect", "review_outcome": "CONFIRMED_DEFECT", "defect_type": []}, "INVALID_DEFECT_TYPE"),
                 ({"review_timestamp": "2026-10-20T12:00:00"}, "INVALID_TIMESTAMP"),
                 ({"inspection_timestamp": "2026-02-30T12:00:00Z"}, "INVALID_TIMESTAMP"),
                 ({"ai_decision": {}}, "INVALID_AI_OUTCOME"), ({"score": True}, "INVALID_SCORE"),
                 ({"camera_id": []}, "INVALID_METADATA_TYPE"), ({"metadata_availability": []}, "INVALID_METADATA_TYPE"),
                 ({"input_image_sha256": "0" * 64}, "IMAGE_HASH_MISMATCH"),
                 ({"input_image_sha256": []}, "INVALID_IMAGE_HASH"), ({"inspection_id": []}, "INVALID_INSPECTION_ID"),
                 ({"image_path": "../private.png"}, "UNSAFE_IMAGE_PATH"),
                 ({"note": "private-token-value"}, "SENSITIVE_METADATA"),
                 ({"capture_source": "https://private.example/path?token=sensitive"}, "SENSITIVE_METADATA"),
                  ({"metadata_availability": {"api_key": "available"}}, "SENSITIVE_METADATA")]
        cases.extend([
            ({"metadata_availability": {"capture_source": []}}, "INVALID_METADATA_TYPE"),
            ({"metadata_availability": {"capture_source": "available"}}, "INCONSISTENT_METADATA"),
            ({"inspection_timestamp": "2026-10-21T12:00:00Z"}, "INCONSISTENT_METADATA"),
            ({"ai_decision": "PASS", "ai_outcome": "FAIL"}, "INCONSISTENT_METADATA"),
        ])
        for updates, expected in cases:
            with self.subTest(updates=updates):
                result = self.package(rows=[record(**updates)])
                self.assertIn(expected, self.codes(result))
                self.assertNotIn("private", json.dumps(result))
                self.assertNotIn("sensitive", json.dumps(result).replace("sensitive metadata", ""))
        row = record()
        del row["review_timestamp"]
        self.assertIn("MISSING_RECORD_FIELD", self.codes(self.package(rows=[row])))
        row = record()
        del row["input_image_sha256"]
        self.assertIn("INVALID_IMAGE_HASH", self.codes(self.package(rows=[row])))

    def test_duplicates_missing_and_unreferenced_images(self):
        result = self.package(rows=[record(), record()])
        self.assertTrue({"DUPLICATE_ID", "DUPLICATE_IMAGE_PATH", "DUPLICATE_IMAGE_HASH"} <= self.codes(result))
        self.assertIn("MISSING_IMAGE", self.codes(self.package(rows=[record(image_path="images/missing.png")])))
        result = self.package(images={"images/one.png": png(), "images/two.png": png()})
        self.assertTrue({"UNREFERENCED_IMAGE", "DUPLICATE_IMAGE_CONTENT"} <= self.codes(result))

    def test_images_fully_decoded_and_pixels_bounded(self):
        raw = b"not an image"
        self.assertIn("INVALID_IMAGE", self.codes(self.package(rows=[record(raw)], images={"images/one.png": raw})))
        self.package()
        result = validate_package(self.path, PackageLimits(max_pixels=11))
        self.assertIn("IMAGE_PIXEL_LIMIT", self.codes(result))
        with patch.object(Image, "MAX_IMAGE_PIXELS", 10):
            self.assertIn("IMAGE_PIXEL_LIMIT", self.codes(validate_package(self.path)))
        raw = png()[:-15]
        self.assertIn("INVALID_IMAGE", self.codes(self.package(rows=[record(raw)], images={"images/one.png": raw})))

    def test_report_integrity_counters(self):
        result = self.package(rows=[record(input_image_sha256="0" * 64)])
        self.assertEqual(result["counts"]["mismatched_hashes"], 1)
        self.assertEqual(result["counts"]["verified_hashes"], 0)
        result = self.package(rows=[record(label="PASS")])
        self.assertEqual(result["counts"]["invalid_labels"], 1)
        result = self.package(extra=[("/outside.png", png())])
        self.assertGreater(result["counts"]["security_failures"], 0)

    def test_preflight_resource_limits(self):
        self.package()
        defaults = PackageLimits()
        for field, value, code in (("max_compressed_bytes", 5, "COMPRESSED_LIMIT"),
                                   ("max_uncompressed_bytes", 5, "UNCOMPRESSED_LIMIT"),
                                   ("max_metadata_bytes", 5, "METADATA_LIMIT"),
                                   ("max_image_bytes", 5, "IMAGE_BYTES_LIMIT"),
                                   ("max_compression_ratio", 1, "COMPRESSION_RATIO_LIMIT")):
            with self.subTest(field=field), patch.object(zipfile.ZipFile, "open", side_effect=AssertionError("Must preflight")):
                result = validate_package(self.path, replace(defaults, **{field: value}))
                self.assertIn(code, self.codes(result))
        self.package(images={"images/one.png": png(), "images/two.png": png((1, 2, 3))})
        self.assertIn("IMAGE_COUNT_LIMIT", self.codes(validate_package(self.path, PackageLimits(max_images=1))))
        self.package(rows=[record(), record()])
        self.assertIn("RECORD_COUNT_LIMIT", self.codes(validate_package(self.path, PackageLimits(max_images=1))))

    def test_crc_corruption_and_encrypted_or_unsupported_preflight(self):
        self.package(compression=zipfile.ZIP_STORED)
        original = self.path.read_bytes()
        damaged = bytearray(original)
        with zipfile.ZipFile(io.BytesIO(original)) as archive:
            info = archive.getinfo("images/one.png")
            offset = info.header_offset
            name_length, extra_length = struct.unpack_from("<HH", damaged, offset + 26)
            damaged[offset + 30 + name_length + extra_length] ^= 1
        self.path.write_bytes(damaged)
        self.assertIn("MEMBER_READ_ERROR", self.codes(validate_package(self.path)))
        for offset, value, code in ((8, 1, "ENCRYPTED_ENTRY"), (10, 99, "UNSUPPORTED_COMPRESSION")):
            damaged = bytearray(original)
            central = damaged.index(b"PK\x01\x02")
            struct.pack_into("<H", damaged, central + offset, value)
            self.path.write_bytes(damaged)
            with patch.object(zipfile.ZipFile, "open", side_effect=AssertionError("Must preflight")):
                self.assertIn(code, self.codes(validate_package(self.path)))

    def test_csv_and_readme_counts(self):
        for csv_text in ("reason,inspection_id\nx,two\n", "inspection_id,reason\none,NO_HUMAN_REVIEW\n", "inspection_id,reason\ntwo,NO_HUMAN_REVIEW\ntwo,NO_HUMAN_REVIEW\n", 'inspection_id,reason\n"unclosed,REASON', "inspection_id,reason\ntwo,REASON,extra\n"):
            self.assertEqual(self.package(exclusions=csv_text)["status"], "INVALID")
        text = "inspection_id,reason\ntwo,NO_HUMAN_REVIEW\n"
        summary = {"included_count": 1, "excluded_count": 1, "exclusion_counts": {"NO_HUMAN_REVIEW": 1}, "export_complete": False}
        result = self.package(exclusions=text, overrides={"README.md": _readme(summary)})
        self.assertEqual(result["errors"], [])
        self.assertIn("INCOMPLETE_EXPORT", self.codes(result, "warnings"))
        self.assertIn("README_COUNTS_MISMATCH", self.codes(self.package(overrides={"README.md": "# no counts"})))

    def test_safe_nested_grouping_and_defect_metadata(self):
        raw = png((90, 50, 10))
        rows = [record(physical_sample_id="sample1", capture_session="session1"),
                record(raw, inspection_id="two", image_path="images/nested/two.png", label="defect", review_outcome="CONFIRMED_DEFECT", defect_type="scratch", physical_sample_id="sample1", capture_session="session1")]
        result = self.package(rows=rows, images={"images/one.png": png(), "images/nested/two.png": raw})
        self.assertEqual(result["errors"], [])
        self.assertIn("REUSED_GROUP", self.codes(result, "warnings"))
        self.assertNotIn("MISSING_GROUPING", self.codes(result, "warnings"))
        self.assertEqual(result, validate_package(self.path))

    def test_invalid_source_and_limits(self):
        self.assertIn("SOURCE_UNREADABLE", self.codes(validate_package(self.path)))
        self.path.write_bytes(b"not zip")
        self.assertIn("INVALID_ZIP", self.codes(validate_package(self.path)))
        for value in (0, -1, True, float("inf")):
            with self.assertRaises(ValueError):
                PackageLimits(max_pixels=value)


if __name__ == "__main__":
    unittest.main()
