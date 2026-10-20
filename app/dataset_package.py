"""Read-only validation of untrusted reviewed-evidence ZIP packages.

No archive paths are extracted and no input values are interpolated into reports.
The digest identifies the bounded snapshot that was actually validated.

The existing efficientad.data.DatasetManifest requires training images and
assigned splits, so candidate packages deliberately do not instantiate it.
Its duplicate/grouping rules are applied here to archive bytes instead of
extracting untrusted files just to call the filesystem discovery helpers.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
import hashlib
from io import BytesIO, StringIO
import json
import math
from pathlib import Path, PureWindowsPath
import re
import stat
import warnings
import zipfile
import zlib

from PIL import Image


@dataclass(frozen=True)
class PackageLimits:
    max_compressed_bytes: int = 64 * 1024 * 1024
    max_uncompressed_bytes: int = 128 * 1024 * 1024
    max_images: int = 500
    max_image_bytes: int = 16 * 1024 * 1024
    max_metadata_bytes: int = 4 * 1024 * 1024
    max_compression_ratio: float = 200
    max_pixels: int = 20_000_000

    def __post_init__(self):
        for name, value in vars(self).items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError("Package limits must be positive finite numbers")
            if name != "max_compression_ratio" and not isinstance(value, int):
                raise ValueError("Package byte, count and pixel limits must be integers")


_REQUIRED = frozenset({"manifest.jsonl", "README.md", "exclusions.csv"})
_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".ppm", ".pgm", ".bmp", ".tif", ".tiff", ".gif", ".img"})
# Mirrors app.api.DEFECT_TYPES without importing the API and its model dependencies.
_DEFECTS = frozenset({"scratch", "dent", "crack", "contamination", "misalignment", "other"})
_GROUPS = ("physical_sample_id", "capture_session", "capture_session_id", "batch_id", "lot_id")
_STRINGS = frozenset({"model_version", "capture_source", "category", "camera_id", "product_id", "dataset_id", "license", *_GROUPS})
_FIELDS = frozenset({"image_path", "inspection_id", "label", "review_outcome", "input_image_sha256", "review_timestamp", "inspection_timestamp", "defect_type", "ai_decision", "ai_outcome", "anomaly_score", "score", "metadata_availability", *_STRINGS})
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}\Z")
_SENSITIVE_KEY = re.compile(r"note|url|token|secret|password|credential|email|authorization|api.?key|private|(?:^|_)path", re.I)
_SENSITIVE_VALUE = re.compile(r"(?:https?://|file://|data:|bearer\s|-----BEGIN |\bsk-[A-Za-z0-9]{12,}|\bAKIA[A-Z0-9]{16}\b|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}|(?:password|token|secret|api_key)\s*[:=])", re.I)


def _safe_path(value):
    return (isinstance(value, str) and bool(value) and not value.startswith("/")
            and not PureWindowsPath(value).drive and "\\" not in value
            and not any(ord(char) < 32 or ord(char) == 127 for char in value)
            and all(part not in {"", ".", ".."} and not part.endswith((" ", ".")) and ":" not in part
                    and not re.fullmatch(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", part, re.I)
                    for part in value.split("/")))


def _sensitive(value):
    if isinstance(value, dict):
        return any((_SENSITIVE_KEY.search(key) and key != "image_path") or _sensitive(item)
                   for key, item in value.items())
    if isinstance(value, list):
        return any(_sensitive(item) for item in value)
    return isinstance(value, str) and (bool(_SENSITIVE_VALUE.search(value)) or value.startswith(("/", "\\")) or bool(PureWindowsPath(value).drive))


def _json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    def constant(_):
        raise ValueError("Nonfinite JSON number")

    result = json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    # JSON's exponent syntax can overflow even without a NaN/Infinity literal.
    def finite(value):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("Nonfinite JSON number")
        if isinstance(value, dict):
            for item in value.values():
                finite(item)
        if isinstance(value, list):
            for item in value:
                finite(item)
    finite(result)
    return result


def _timestamp(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})", value):
        return False
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).utcoffset() is not None
    except ValueError:
        return False


def validate_package(path: str | Path, limits: PackageLimits | None = None) -> dict:
    """Return deterministic status, snapshot SHA-256, counts and redacted issues.

    ``record_index`` is the one-based JSONL line (or CSV data-row) number.
    Structural ZIP failures stop before any member is decompressed. A source
    that cannot be fully snapshotted within the limit has a null source digest.
    This function never assigns splits or writes to the filesystem.
    """
    limits = limits or PackageLimits()
    report = {"status": "INVALID", "source_sha256": None,
              "counts": {"records": 0, "images": 0, "normal": 0, "defect": 0, "excluded": 0,
                         "archive_members": 0, "valid_images": 0, "invalid_images": 0,
                         "verified_hashes": 0, "mismatched_hashes": 0,
                         "duplicate_image_hashes": 0, "invalid_labels": 0,
                         "metadata_issues": 0, "exclusion_inconsistencies": 0,
                         "security_failures": 0},
              "errors": [], "warnings": []}

    def issue(code, message, index=None, *, warning=False):
        item = {"code": code, "message": message}
        if index is not None:
            item["record_index"] = index
        report["warnings" if warning else "errors"].append(item)

    def finish():
        codes = [item["code"] for item in report["errors"] + report["warnings"]]
        report["counts"]["invalid_labels"] = sum(code in {"INVALID_LABEL", "REVIEW_LABEL_MISMATCH"} for code in codes)
        report["counts"]["metadata_issues"] = sum(code in {"MISSING_RECORD_FIELD", "INVALID_METADATA_TYPE", "INVALID_TIMESTAMP", "INVALID_AI_OUTCOME", "INVALID_SCORE", "UNSUPPORTED_METADATA", "MISSING_GROUPING", "MISSING_PROVENANCE", "INCONSISTENT_METADATA"} for code in codes)
        report["counts"]["exclusion_inconsistencies"] = sum(code in {"README_COUNTS_MISMATCH", "INVALID_EXCLUSION", "INVALID_EXCLUSIONS_CSV", "DUPLICATE_EXCLUSION_ID"} for code in codes)
        report["counts"]["security_failures"] = sum(code in {"UNSAFE_PATH", "UNSAFE_IMAGE_PATH", "SPECIAL_ENTRY", "DUPLICATE_ENTRY", "SENSITIVE_METADATA", "ENCRYPTED_ENTRY", "UNSUPPORTED_COMPRESSION"} or code.endswith("LIMIT") for code in codes)
        report["status"] = "INVALID" if report["errors"] else ("VALID_WITH_WARNINGS" if report["warnings"] else "VALID")
        return report

    try:
        with Path(path).open("rb") as stream:
            snapshot = stream.read(limits.max_compressed_bytes + 1)
    except (OSError, ValueError):
        issue("SOURCE_UNREADABLE", "Package source could not be read.")
        return finish()
    if len(snapshot) > limits.max_compressed_bytes:
        issue("COMPRESSED_LIMIT", "Package exceeds the compressed byte limit.")
        return finish()
    report["source_sha256"] = hashlib.sha256(snapshot).hexdigest()
    try:
        archive = zipfile.ZipFile(BytesIO(snapshot))
    except (OSError, ValueError, zipfile.BadZipFile):
        issue("INVALID_ZIP", "Package is not a readable ZIP archive.")
        return finish()
    with archive:
        entries = archive.infolist()
        report["counts"]["archive_members"] = len(entries)
        # Directories also consume the entry budget; arbitrarily many empty
        # entries must not bypass the image-count resource bound.
        if len(entries) > limits.max_images * 2 + len(_REQUIRED) + 1:
            issue("ENTRY_LIMIT", "Package exceeds the archive entry limit.")
            return finish()
        seen = set()
        files = {}
        image_names = set()
        total = 0
        metadata_total = 0
        for info in entries:
            name = info.filename
            canonical = name[:-1] if info.is_dir() else name
            if not _safe_path(canonical) or info.orig_filename != name:
                issue("UNSAFE_PATH", "Archive contains an unsafe member path.")
            portable = canonical.casefold()
            if portable in seen:
                issue("DUPLICATE_ENTRY", "Archive contains duplicate member paths.")
            seen.add(portable)
            mode = info.external_attr >> 16
            kind = stat.S_IFMT(mode)
            if kind not in {0, stat.S_IFREG, stat.S_IFDIR} or (kind == stat.S_IFDIR) != info.is_dir() and kind != 0:
                issue("SPECIAL_ENTRY", "Archive contains a symbolic link or special entry.")
            if info.flag_bits & 1:
                issue("ENCRYPTED_ENTRY", "Encrypted archive members are unsupported.")
            if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                issue("UNSUPPORTED_COMPRESSION", "Archive member compression is unsupported.")
            if info.file_size > max(1, info.compress_size) * limits.max_compression_ratio:
                issue("COMPRESSION_RATIO_LIMIT", "Archive member exceeds the compression ratio limit.")
            total += info.file_size
            if info.is_dir():
                if canonical != "images" and not canonical.startswith("images/"):
                    issue("UNEXPECTED_FILE", "Archive contains an unexpected directory.")
                if info.file_size:
                    issue("SPECIAL_ENTRY", "Archive directory contains unexpected data.")
                continue
            files[name] = info
            if name in _REQUIRED:
                metadata_total += info.file_size
                if info.file_size > limits.max_metadata_bytes:
                    issue("METADATA_LIMIT", "Package metadata exceeds the byte limit.")
            elif name.startswith("images/") and Path(name).suffix.lower() in _SUFFIXES:
                image_names.add(name)
                if info.file_size > limits.max_image_bytes:
                    issue("IMAGE_BYTES_LIMIT", "Image exceeds the member byte limit.")
            else:
                issue("UNEXPECTED_FILE", "Archive contains an unexpected file.")
        report["counts"]["images"] = len(image_names)
        if total > limits.max_uncompressed_bytes:
            issue("UNCOMPRESSED_LIMIT", "Package exceeds the uncompressed byte limit.")
        if metadata_total > limits.max_metadata_bytes:
            issue("METADATA_LIMIT", "Package metadata exceeds the total byte limit.")
        if len(image_names) > limits.max_images:
            issue("IMAGE_COUNT_LIMIT", "Package exceeds the image count limit.")
        if not _REQUIRED <= files.keys():
            issue("MISSING_REQUIRED_FILE", "Package is missing a required metadata file.")
        if report["errors"]:
            return finish()
        contents = {}
        actual_total = 0
        for info in entries:
            cap = limits.max_image_bytes if info.filename in image_names else limits.max_metadata_bytes
            try:
                with archive.open(info) as stream:
                    raw = stream.read(min(cap, limits.max_uncompressed_bytes - actual_total) + 1)
                actual_total += len(raw)
                if len(raw) > cap or actual_total > limits.max_uncompressed_bytes or len(raw) != info.file_size:
                    issue("MEMBER_READ_LIMIT", "Archive member exceeds its declared or allowed size.")
                    return finish()
                if not info.is_dir():
                    contents[info.filename] = raw
            except (OSError, ValueError, RuntimeError, NotImplementedError, zipfile.BadZipFile, EOFError, zlib.error):
                issue("MEMBER_READ_ERROR", "Archive member failed integrity validation.")
        if report["errors"]:
            return finish()

    texts = {}
    for name in sorted(_REQUIRED):
        try:
            texts[name] = contents[name].decode("utf-8")
        except UnicodeError:
            issue("INVALID_ENCODING", "Metadata must contain valid UTF-8 text.")
    if report["errors"]:
        return finish()
    ids, paths, hashes = set(), set(), set()
    groups = {}
    missing_groups = False
    defect_types = set()
    for index, line in enumerate(texts["manifest.jsonl"].splitlines(), 1):
        report["counts"]["records"] += 1
        if index > limits.max_images:
            issue("RECORD_COUNT_LIMIT", "Manifest exceeds the record count limit.")
            break
        try:
            row = _json(line)
            if not isinstance(row, dict):
                raise ValueError("Object required")
        except (ValueError, RecursionError):
            issue("INVALID_JSONL", "Manifest record is not a strict JSON object.", index)
            continue
        if _sensitive(row):
            issue("SENSITIVE_METADATA", "Manifest contains sensitive metadata.", index)
        if row.keys() - _FIELDS:
            issue("UNSUPPORTED_METADATA", "Manifest contains unsupported metadata fields.", index)
        required = {"image_path", "inspection_id", "label", "review_outcome", "input_image_sha256", "review_timestamp"}
        if not required <= row.keys():
            issue("MISSING_RECORD_FIELD", "Manifest record is missing a required field.", index)
        identifier = row.get("inspection_id")
        if not isinstance(identifier, str) or not _ID.fullmatch(identifier):
            issue("INVALID_INSPECTION_ID", "Manifest inspection identifier is invalid.", index)
        elif identifier in ids:
            issue("DUPLICATE_ID", "Manifest repeats an inspection identifier.", index)
        else:
            ids.add(identifier)
        image_path = row.get("image_path")
        if not _safe_path(image_path) or not image_path.startswith("images/"):
            issue("UNSAFE_IMAGE_PATH", "Manifest image path is unsafe.", index)
        elif image_path in paths:
            issue("DUPLICATE_IMAGE_PATH", "Manifest repeats an image path.", index)
        else:
            paths.add(image_path)
            if image_path not in image_names:
                issue("MISSING_IMAGE", "Manifest references a missing image.", index)
        label = row.get("label")
        if not isinstance(label, str) or label not in {"normal", "defect"}:
            issue("INVALID_LABEL", "Manifest label is unsupported.", index)
        else:
            report["counts"][label] += 1
            if row.get("review_outcome") != {"normal": "CONFIRMED_NORMAL", "defect": "CONFIRMED_DEFECT"}[label]:
                issue("REVIEW_LABEL_MISMATCH", "Label requires a consistent definitive human review.", index)
        defect = row.get("defect_type")
        if defect is not None and (label != "defect" or not isinstance(defect, str) or defect not in _DEFECTS):
            issue("INVALID_DEFECT_TYPE", "Defect type is unsupported or inconsistent with the label.", index)
        elif label == "defect" and defect:
            defect_types.add(defect)
        if not _timestamp(row.get("review_timestamp")) or row.get("inspection_timestamp") is not None and not _timestamp(row["inspection_timestamp"]):
            issue("INVALID_TIMESTAMP", "Timestamp must use timezone-aware ISO format.", index)
        for key in ("ai_decision", "ai_outcome"):
            value = row.get(key)
            if value is not None and (not isinstance(value, str) or value not in {"PASS", "FAIL", "UNVERIFIED"}):
                issue("INVALID_AI_OUTCOME", "AI provenance outcome is unsupported.", index)
        if "ai_decision" in row and "ai_outcome" in row and row["ai_decision"] != row["ai_outcome"]:
            issue("INCONSISTENT_METADATA", "Original AI outcome fields disagree.", index)
        for key in ("anomaly_score", "score"):
            value = row.get(key)
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or isinstance(value, float) and not math.isfinite(value)):
                issue("INVALID_SCORE", "Score must be a finite number or null.", index)
        for key in sorted(_STRINGS):
            value = row.get(key)
            if value is not None and (not isinstance(value, str) or not value.strip() or len(value) > 256):
                issue("INVALID_METADATA_TYPE", "Optional metadata must be bounded nonempty text or null.", index)
        availability = row.get("metadata_availability")
        if availability is not None and (not isinstance(availability, dict) or any(not isinstance(value, str) or value not in {"available", "unavailable"} for value in availability.values())):
            issue("INVALID_METADATA_TYPE", "Metadata availability must contain supported status values.", index)
        if any(row.get(key) in (None, "unknown") for key in ("inspection_timestamp", "capture_source", "model_version")):
            issue("MISSING_PROVENANCE", "Some original inspection provenance is unavailable; retain this limitation.", index, warning=True)
        if isinstance(availability, dict):
            for key in ("inspection_timestamp", "capture_source"):
                present = row.get(key) not in (None, "unknown")
                if isinstance(availability.get(key), str) and availability[key] in {"available", "unavailable"} and (availability[key] == "available") != present:
                    issue("INCONSISTENT_METADATA", "Metadata availability disagrees with the recorded value.", index)
        if _timestamp(row.get("inspection_timestamp")) and _timestamp(row.get("review_timestamp")):
            if datetime.fromisoformat(row["review_timestamp"].replace("Z", "+00:00")) < datetime.fromisoformat(row["inspection_timestamp"].replace("Z", "+00:00")):
                issue("INCONSISTENT_METADATA", "Human review timestamp precedes the original inspection.", index)
        digest = row.get("input_image_sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            issue("INVALID_IMAGE_HASH", "Image digest must be a lowercase SHA-256 value.", index)
        else:
            if digest in hashes:
                issue("DUPLICATE_IMAGE_HASH", "Manifest repeats image content.", index)
            hashes.add(digest)
            if isinstance(image_path, str) and image_path in image_names and hashlib.sha256(contents[image_path]).hexdigest() != digest:
                report["counts"]["mismatched_hashes"] += 1
                issue("IMAGE_HASH_MISMATCH", "Image bytes do not match the manifest digest.", index)
            elif isinstance(image_path, str) and image_path in image_names:
                report["counts"]["verified_hashes"] += 1
        present_groups = [key for key in _GROUPS if isinstance(row.get(key), str) and row[key].strip()]
        missing_groups |= ("physical_sample_id" not in present_groups
                           or not {"capture_session", "capture_session_id"}.intersection(present_groups))
        for key in present_groups:
            group = (key, row[key])
            groups[group] = groups.get(group, 0) + 1
    if image_names - paths:
        issue("UNREFERENCED_IMAGE", "Package contains images not referenced by the manifest.")
    actual_hashes = set()
    for name in sorted(image_names):
        raw = contents[name]
        digest = hashlib.sha256(raw).hexdigest()
        if digest in actual_hashes:
            report["counts"]["duplicate_image_hashes"] += 1
            issue("DUPLICATE_IMAGE_CONTENT", "Package contains duplicate image bytes.")
        actual_hashes.add(digest)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(BytesIO(raw)) as image:
                    pixels = 0
                    for frame in range(getattr(image, "n_frames", 1)):
                        image.seek(frame)
                        pixels += image.width * image.height
                        if pixels > limits.max_pixels:
                            raise Image.DecompressionBombError("Pixel limit")
                        image.load()
                with Image.open(BytesIO(raw)) as image:
                    image.verify()
            report["counts"]["valid_images"] += 1
        except (Image.DecompressionBombError, Image.DecompressionBombWarning):
            report["counts"]["invalid_images"] += 1
            issue("IMAGE_PIXEL_LIMIT", "Image exceeds safe decoded pixel limits.")
        except (OSError, ValueError, EOFError, SyntaxError):
            report["counts"]["invalid_images"] += 1
            issue("INVALID_IMAGE", "Image could not be fully decoded and verified.")
    exclusion_ids = set()
    reasons = {}
    try:
        reader = csv.reader(StringIO(texts["exclusions.csv"], newline=""), strict=True)
        if next(reader, None) != ["inspection_id", "reason"]:
            raise ValueError("CSV header")
        for index, values in enumerate(reader, 1):
            report["counts"]["excluded"] += 1
            if len(values) != 2 or not _ID.fullmatch(values[0]) or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,99}", values[1]):
                issue("INVALID_EXCLUSION", "Exclusion record fields are invalid.", index)
                continue
            identifier, reason = values
            if identifier in exclusion_ids or identifier in ids:
                issue("DUPLICATE_EXCLUSION_ID", "Exclusion identifier is duplicated or also included.", index)
            exclusion_ids.add(identifier)
            reasons[reason] = reasons.get(reason, 0) + 1
    except (ValueError, csv.Error):
        issue("INVALID_EXCLUSIONS_CSV", "Exclusion CSV must use the required strict two-column format.")
    readme = texts["README.md"]
    try:
        values = {}
        for key in ("Included", "Excluded", "Complete", "Exclusion counts"):
            matches = re.findall(r"^- " + key + r": (.+)$", readme, re.M)
            if len(matches) != 1:
                raise ValueError("README summary")
            values[key] = matches[0]
        count_json = values["Exclusion counts"]
        if not count_json.startswith("`") or not count_json.endswith("`"):
            raise ValueError("README counts")
        counts = _json(count_json[1:-1])
        if (not isinstance(counts, dict) or any(type(value) is not int or value < 0 for value in counts.values())
                or counts != reasons or values["Included"] != str(report["counts"]["records"])
                or values["Excluded"] != str(report["counts"]["excluded"]) or values["Complete"] not in {"True", "False"}):
            raise ValueError("README counts")
        if values["Complete"] == "False":
            issue("INCOMPLETE_EXPORT", "Package declares an incomplete export.", warning=True)
    except (ValueError, RecursionError):
        issue("README_COUNTS_MISMATCH", "README summary is missing, malformed or inconsistent with package counts.")
    if missing_groups:
        issue("MISSING_GROUPING", "Some records lack sample or session grouping; leakage cannot be assessed.", warning=True)
    if any(count > 1 for count in groups.values()):
        issue("REUSED_GROUP", "Repeated sample or capture groups must be kept together in future splits.", warning=True)
    counts = report["counts"]
    if counts["records"] < 20:
        issue("LOW_SAMPLE_COUNT", "Package has too few records for reliable dataset evaluation.", warning=True)
    if not counts["normal"] or not counts["defect"] or min(counts["normal"], counts["defect"]) * 5 < max(counts["normal"], counts["defect"]):
        issue("CLASS_BALANCE", "Class coverage is missing or substantially imbalanced.", warning=True)
    if defect_types != _DEFECTS:
        issue("DEFECT_COVERAGE", "Controlled defect categories are not fully represented.", warning=True)
    issue("PROVENANCE_NOT_VERIFIED", "Human-review identity and capture provenance require independent verification.", warning=True)
    return finish()
