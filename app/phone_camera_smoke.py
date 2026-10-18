"""Capture one validated frame from a phone's local MJPEG stream."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from .camera import FramePolicy, FreshFrameSelector, MjpegCameraSource


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Smoke-test a local phone MJPEG camera")
    parser.add_argument("--url", required=True, help="runtime-only phone MJPEG URL, for example http://phone-ip:8080/video")
    parser.add_argument("--output", type=Path, default=Path("data/phone-camera-frame.ppm"))
    parser.add_argument("--max-age-ms", type=int, default=1000)
    parser.add_argument("--timeout-ms", type=int, default=5000)
    return parser


def write_ppm(path: Path, frame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    height, width, _ = frame.shape
    with path.open("wb") as stream:
        stream.write(f"P6\n{width} {height}\n255\n".encode("ascii"))
        stream.write(frame.tobytes())


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source = MjpegCameraSource(args.url)
    selector = FreshFrameSelector(FramePolicy(max_age_ms=args.max_age_ms))
    try:
        frame = source.read(args.timeout_ms)
        if frame is None:
            raise SystemExit(f"camera read failed: {source.health()}")
        accepted = selector.accept(frame, now=datetime.now(timezone.utc))
        write_ppm(args.output, accepted.frame)
        print({"output": str(args.output), "shape": accepted.frame.shape, "sequence": accepted.sequence_no, "health": source.health()})
    finally:
        source.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
