"""Bounded, redacted export of eligible human-reviewed inspection evidence."""

from __future__ import annotations

import base64
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from io import BytesIO, StringIO
import json
from pathlib import Path
import zipfile
from typing import Any

from PIL import Image

from .persistence import InspectionRecord, InspectionReview, InspectionStore


MAX_EXPORT_RECORDS = 100
MAX_EXPORT_BYTES = 64 * 1024 * 1024
MAX_PREVIEW_RECORDS = 1000


@dataclass(frozen=True)
class ExportResult:
    archive: bytes
    filename: str
    summary: dict[str, Any]


def _safe_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _safe_json(v) for k, v in value.items() if not any(x in str(k).lower() for x in ("note", "path", "url", "token", "secret", "password", "credential"))}
    if isinstance(value, list):
        return [_safe_json(item) for item in value]
    return value if isinstance(value, (str, int, float, bool)) or value is None else None


def _created_payload(store: InspectionStore, inspection_id: str) -> dict[str, Any]:
    for event in store.events(inspection_id):
        if event["event_type"] == "inspection.created":
            payload = event["payload"]
            result = dict(payload) if isinstance(payload, dict) else {}
            result.setdefault("created_at", event.get("created_at"))
            return result
    return {}


def _image_bytes(record: InspectionRecord, created: dict[str, Any], image_root: Path | None) -> tuple[bytes | None, str | None]:
    encoded = record.evidence.get("input_image_data")
    if isinstance(encoded, str) and encoded.startswith("data:"):
        try:
            header, value = encoded.split(",", 1)
            if ";base64" not in header:
                return None, "INVALID_IMAGE_DATA"
            return base64.b64decode(value, validate=True), None
        except (ValueError, base64.binascii.Error):
            return None, "INVALID_IMAGE_DATA"
    image_path = created.get("image_path")
    if not isinstance(image_path, str) or image_root is None:
        return None, "EVIDENCE_UNAVAILABLE"
    candidate = (image_root / image_path).resolve()
    try:
        candidate.relative_to(image_root)
    except ValueError:
        return None, "UNSAFE_EVIDENCE_PATH"
    try:
        return candidate.read_bytes(), None
    except OSError:
        return None, "EVIDENCE_UNAVAILABLE"


def _validate_image(raw: bytes) -> str | None:
    try:
        with Image.open(BytesIO(raw)) as image:
            image.verify()
    except (OSError, ValueError):
        return "INVALID_IMAGE"
    return None


def _image_suffix(raw: bytes) -> str:
    try:
        with Image.open(BytesIO(raw)) as image:
            return {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp", "PPM": ".ppm"}.get(image.format or "", ".img")
    except (OSError, ValueError):
        return ".img"


def _recorded_hash(record: InspectionRecord, review: InspectionReview, created: dict[str, Any]) -> str | None:
    if review.input_image_hash:
        return review.input_image_hash
    value = created.get("image_sha256")
    return value if isinstance(value, str) and value else None


def _candidate(store: InspectionStore, record: InspectionRecord, image_root: Path | None) -> tuple[dict[str, Any] | None, str | None, bytes | None]:
    reviews = store.reviews(record.inspection_id)
    if not reviews:
        return None, "NO_HUMAN_REVIEW", None
    outcomes = {review.outcome for review in reviews}
    if len(outcomes) > 1:
        return None, "CONFLICTING_REVIEWS", None
    latest = reviews[-1]
    if latest.outcome not in {"CONFIRMED_NORMAL", "CONFIRMED_DEFECT"}:
        return None, "LATEST_REVIEW_NOT_DEFINITIVE", None
    created = _created_payload(store, record.inspection_id)
    raw, reason = _image_bytes(record, created, image_root)
    if reason:
        return None, reason, None
    assert raw is not None
    reason = _validate_image(raw)
    if reason:
        return None, reason, None
    actual = hashlib.sha256(raw).hexdigest()
    expected = _recorded_hash(record, latest, created)
    if not expected:
        return None, "IMAGE_HASH_UNAVAILABLE", None
    encoded = record.evidence.get("input_image_data")
    encoded_hash = hashlib.sha256(encoded.encode("utf-8")).hexdigest() if isinstance(encoded, str) else None
    if expected not in {actual, encoded_hash}:
        return None, "IMAGE_HASH_MISMATCH", None
    metadata = {
        "inspection_id": record.inspection_id,
        "label": "normal" if latest.outcome == "CONFIRMED_NORMAL" else "defect",
        "review_outcome": latest.outcome,
        "defect_type": latest.defect_type,
        "review_timestamp": latest.created_at,
        "input_image_sha256": actual,
        "ai_decision": record.outcome,
        "anomaly_score": record.score,
        "model_version": record.model_version,
        "inspection_timestamp": created.get("created_at") if isinstance(created.get("created_at"), str) else None,
        "capture_source": created.get("source") if isinstance(created.get("source"), str) else "unknown",
        "metadata_availability": {
            "inspection_timestamp": "available" if isinstance(created.get("created_at"), str) else "unavailable",
            "capture_source": "available" if isinstance(created.get("source"), str) else "unavailable",
            "reviewer_identity": "unavailable",
        },
    }
    return _safe_json(metadata), None, raw


def _summary(included: list[dict[str, Any]], exclusions: list[dict[str, str]], *, complete: bool, limit: int, byte_limit: int) -> dict[str, Any]:
    return {"included_count": len(included), "excluded_count": len(exclusions), "exclusion_counts": {reason: sum(item["reason"] == reason for item in exclusions) for reason in sorted({item["reason"] for item in exclusions})}, "export_complete": complete, "record_limit": limit, "byte_limit": byte_limit}


def collect(store: InspectionStore, *, image_root: str | Path | None = None, limit: int = MAX_EXPORT_RECORDS, byte_limit: int = MAX_EXPORT_BYTES, filters: dict[str, str] | None = None) -> tuple[list[dict[str, Any]], list[dict[str, str]], dict[str, bytes]]:
    if not 1 <= limit <= MAX_EXPORT_RECORDS:
        raise ValueError(f"limit must be between 1 and {MAX_EXPORT_RECORDS}")
    if not 1 <= byte_limit <= MAX_EXPORT_BYTES:
        raise ValueError(f"byte_limit must be between 1 and {MAX_EXPORT_BYTES}")
    root = Path(image_root).resolve() if image_root is not None else None
    included: list[dict[str, Any]] = []
    exclusions: list[dict[str, str]] = []
    images: dict[str, bytes] = {}
    seen_hashes: set[str] = set()
    for record in store.list(limit=limit):
        reviews = store.reviews(record.inspection_id)
        latest = reviews[-1] if reviews else None
        if filters and ((filters.get("review_outcome") and (latest.outcome if latest else None) != filters["review_outcome"]) or (filters.get("ai_outcome") and record.outcome != filters["ai_outcome"])):
            continue
        metadata, reason, raw = _candidate(store, record, root)
        if reason:
            exclusions.append({"inspection_id": record.inspection_id, "reason": reason})
            continue
        assert metadata is not None and raw is not None
        digest = metadata["input_image_sha256"]
        if digest in seen_hashes:
            exclusions.append({"inspection_id": record.inspection_id, "reason": "DUPLICATE_IMAGE_HASH"})
            continue
        if sum(len(value) for value in images.values()) + len(raw) > byte_limit:
            exclusions.append({"inspection_id": record.inspection_id, "reason": "BYTE_LIMIT_EXCEEDED"})
            continue
        seen_hashes.add(digest)
        archive_name = f"images/{len(included) + 1:06d}-{record.inspection_id}{_image_suffix(raw)}"
        metadata["image_path"] = archive_name
        included.append(metadata)
        images[archive_name] = raw
    return included, exclusions, images


def build(store: InspectionStore, *, image_root: str | Path | None = None, limit: int = MAX_EXPORT_RECORDS, byte_limit: int = MAX_EXPORT_BYTES, filters: dict[str, str] | None = None) -> ExportResult:
    included, exclusions, images = collect(store, image_root=image_root, limit=limit, byte_limit=byte_limit, filters=filters)
    summary = _summary(included, exclusions, complete=True, limit=limit, byte_limit=byte_limit)
    output = BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, raw in images.items():
            archive.writestr(path, raw)
        archive.writestr("manifest.jsonl", "".join(json.dumps(item, sort_keys=True) + "\n" for item in included))
        exclusions_csv = StringIO()
        writer = csv.DictWriter(exclusions_csv, fieldnames=["inspection_id", "reason"])
        writer.writeheader()
        writer.writerows(exclusions)
        archive.writestr("exclusions.csv", exclusions_csv.getvalue())
        archive.writestr("README.md", _readme(summary))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return ExportResult(output.getvalue(), f"reviewed-inspection-evidence-{stamp}.zip", summary)


def _readme(summary: dict[str, Any]) -> str:
    return f"""# Human-reviewed inspection evidence\n\nThis package contains candidate evidence for future dataset validation and model evaluation. It is **not approved training data** and does not assign train, validation, or test splits. It does not qualify, calibrate, deploy, or release a model.\n\n## Labels and eligibility\n\n`normal` comes from `CONFIRMED_NORMAL`; `defect` comes from `CONFIRMED_DEFECT`. An image was included only when readable, valid, hash-verifiable, definitively reviewed, and free of conflicting review outcomes. AI decisions are preserved as provenance and never used as the label.\n\n## Results\n\n- Included: {summary['included_count']}\n- Excluded: {summary['excluded_count']}\n- Complete: {summary['export_complete']}\n- Exclusion counts: `{json.dumps(summary['exclusion_counts'], sort_keys=True)}`\n\nExcluded records are listed in `exclusions.csv`. Reviewer identity is not independently verified; human reviews may contain errors. Do not mix this package into an existing dataset without separately checking duplicates, physical-sample leakage, capture-session leakage, and provenance.\n"""
