"""CLI entry point for starting a reviewed EfficientAD-backed API."""

from __future__ import annotations

import argparse
from pathlib import Path

from .api import serve_api
from .efficientad.release import load_reviewed_release


def parse_threshold(value: str) -> tuple[str, tuple[float, float]]:
    """Parse ``category:pass_threshold:fail_threshold``."""
    parts = value.split(":")
    if len(parts) != 3 or not parts[0].strip():
        raise argparse.ArgumentTypeError("threshold must be category:pass_threshold:fail_threshold")
    try:
        thresholds = (float(parts[1]), float(parts[2]))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("threshold values must be numbers") from exc
    if thresholds[0] >= thresholds[1]:
        raise argparse.ArgumentTypeError("pass threshold must be less than fail threshold")
    return parts[0].strip(), thresholds


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve the reviewed native EfficientAD inspection API")
    parser.add_argument("--metadata", type=Path, required=True, help="path to reviewed run_metadata.json")
    parser.add_argument("--artifacts", type=Path, required=True, help="root of downloaded EfficientAD artifacts")
    parser.add_argument("--teacher", type=Path, required=True, help="path to teacher_small.pth")
    parser.add_argument("--image-root", type=Path, required=True, help="directory containing request images")
    parser.add_argument("--threshold", action="append", type=parse_threshold, required=True, help="category:pass:fail; repeat per category")
    parser.add_argument("--device", default="cpu", choices=("cpu", "cuda"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    thresholds = dict(args.threshold)
    release = load_reviewed_release(args.metadata, args.artifacts, args.teacher, thresholds)
    api = release.create_api(device=args.device, image_root=args.image_root)
    serve_api(api, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
