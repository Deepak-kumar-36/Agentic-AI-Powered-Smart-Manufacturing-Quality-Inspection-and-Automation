"""CLI entry point for starting a reviewed EfficientAD-backed API."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from .api import serve_api
from .efficientad.release import load_reviewed_release
from .persistence import InspectionStore
from .hardware import open_serial_bridge


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
    parser.add_argument("--evidence-root", action="append", type=Path, default=[], help="additional managed directory for resolving recorded evidence paths")
    parser.add_argument("--db", type=Path, default=Path("data/inspection.sqlite3"), help="durable SQLite database path")
    parser.add_argument("--threshold", action="append", type=parse_threshold, required=True, help="category:pass:fail; repeat per category")
    parser.add_argument("--device", default="cpu", choices=("cpu", "cuda"))
    parser.add_argument("--hardware-serial-port", type=str, default=None, help="opt-in ESP32 serial port")
    parser.add_argument("--hardware-baudrate", type=int, default=115200)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    return parser


def environment_flag(name: str, environ: dict[str, str] | None = None) -> bool:
    value = (environ or os.environ).get(name, "false").strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off", ""}:
        return False
    raise ValueError(f"{name} must be true or false")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    thresholds = dict(args.threshold)
    try:
        auto_capture_on_ir = environment_flag("AUTO_CAPTURE_ON_IR")
    except ValueError as exc:
        build_parser().error(str(exc))
    auto_capture_category = os.environ.get("AUTO_CAPTURE_CATEGORY", "").strip()
    if auto_capture_on_ir:
        if not args.hardware_serial_port:
            build_parser().error("AUTO_CAPTURE_ON_IR requires --hardware-serial-port")
        if auto_capture_category not in thresholds:
            build_parser().error("AUTO_CAPTURE_CATEGORY must be one of the configured --threshold categories")
    release = load_reviewed_release(args.metadata, args.artifacts, args.teacher, thresholds)
    args.db.parent.mkdir(parents=True, exist_ok=True)
    hardware = open_serial_bridge(args.hardware_serial_port, args.hardware_baudrate) if args.hardware_serial_port else None
    api = release.create_api(device=args.device, image_root=args.image_root, evidence_roots=args.evidence_root, hardware=hardware, store=InspectionStore(args.db), auto_capture_on_ir=auto_capture_on_ir, auto_capture_category=auto_capture_category or None)
    serve_api(api, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
