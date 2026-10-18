"""Run supervised, read-only phone-camera inspections."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import time
from uuid import uuid4

from .api import InspectionApi
from .camera import CameraError, CameraSource, FramePolicy, FreshFrameSelector, MjpegCameraSource
from .efficientad.release import load_reviewed_release
from .persistence import InspectionStore


def capture_and_submit(
    source: CameraSource,
    api: InspectionApi,
    *,
    category: str,
    image_dir: Path,
    count: int = 1,
    timeout_ms: int = 5000,
    max_age_ms: int = 1000,
    interval_ms: int = 0,
) -> list[dict[str, object]]:
    """Capture frames, validate them, and submit server-scored inspections.

    This function has no controller or actuation path. Capture failures are
    reported as ``UNVERIFIED``-like local results and never submitted as PASS.
    """
    if count < 1 or timeout_ms < 1 or interval_ms < 0:
        raise ValueError("count and timeout must be positive; interval cannot be negative")
    image_dir.mkdir(parents=True, exist_ok=True)
    selector = FreshFrameSelector(FramePolicy(max_age_ms=max_age_ms))
    results: list[dict[str, object]] = []
    for index in range(count):
        started = time.monotonic()
        try:
            frame = source.read(timeout_ms)
            if frame is None:
                result = {"outcome": "UNVERIFIED", "reason_codes": ["CAMERA_FRAME_UNAVAILABLE"]}
            else:
                accepted = selector.accept(frame, now=datetime.now(timezone.utc))
                image_path = image_dir / f"{accepted.camera_id.replace('/', '_')}-{accepted.sequence_no}-{uuid4().hex}.png"
                from PIL import Image

                Image.fromarray(accepted.frame, mode="RGB").save(image_path)
                if api.image_root is not None:
                    try:
                        request_image_path = image_path.resolve().relative_to(api.image_root.resolve()).as_posix()
                    except ValueError as exc:
                        raise ValueError("shadow image directory must be inside the API image root") from exc
                else:
                    request_image_path = str(image_path)
                status, payload = api.handle(
                    "POST",
                    "/api/v1/inspections",
                    body=(f'{{"category":"{category}","image_path":"{request_image_path}"}}').encode(),
                    headers={"Idempotency-Key": f"phone-shadow-{uuid4().hex}"},
                )
                result = {"http_status": status, **payload, "image_path": str(image_path)}
        except (CameraError, OSError, ValueError) as exc:
            result = {"outcome": "UNVERIFIED", "reason_codes": ["CAMERA_FRAME_INVALID"], "error": str(exc)}
        result["capture_latency_ms"] = round((time.monotonic() - started) * 1000, 2)
        results.append(result)
        if index + 1 < count and interval_ms:
            time.sleep(interval_ms / 1000)
    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run supervised read-only phone-camera inspections")
    parser.add_argument("--url", required=True, help="runtime-only local phone MJPEG URL")
    parser.add_argument("--category", required=True, choices=("bottle", "screw", "capsule"))
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--teacher", type=Path, required=True)
    parser.add_argument("--image-root", type=Path, required=True)
    parser.add_argument("--db", type=Path, default=Path("data/inspection.sqlite3"))
    parser.add_argument("--threshold", action="append", required=True, help="category:pass:fail; repeat for every release category")
    parser.add_argument("--device", default="cpu", choices=("cpu", "cuda"))
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--interval-ms", type=int, default=0)
    parser.add_argument("--timeout-ms", type=int, default=5000)
    parser.add_argument("--max-age-ms", type=int, default=1000)
    return parser


def _thresholds(values: list[str]) -> dict[str, tuple[float, float]]:
    parsed: dict[str, tuple[float, float]] = {}
    for value in values:
        category, pass_value, fail_value = value.split(":")
        thresholds = (float(pass_value), float(fail_value))
        if thresholds[0] >= thresholds[1]:
            raise ValueError("pass threshold must be less than fail threshold")
        parsed[category] = thresholds
    return parsed


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    release = load_reviewed_release(args.metadata, args.artifacts, args.teacher, _thresholds(args.threshold))
    args.image_root.mkdir(parents=True, exist_ok=True)
    args.db.parent.mkdir(parents=True, exist_ok=True)
    api = release.create_api(device=args.device, image_root=args.image_root, store=InspectionStore(args.db))
    source = MjpegCameraSource(args.url)
    try:
        for result in capture_and_submit(source, api, category=args.category, image_dir=args.image_root, count=args.count, timeout_ms=args.timeout_ms, max_age_ms=args.max_age_ms, interval_ms=args.interval_ms):
            print(result)
    finally:
        source.close()
        api.store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
