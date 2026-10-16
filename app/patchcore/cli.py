"""Small offline CLI for dataset inventory; benchmark commands stay explicit."""

from __future__ import annotations

import argparse
import json

from .core import PatchCoreConfig
from .dataset import discover_mvtec


def main() -> int:
    parser = argparse.ArgumentParser(prog="patchcore")
    subparsers = parser.add_subparsers(dest="command", required=True)
    inventory = subparsers.add_parser("inventory", help="validate and inventory an MVTec AD root")
    inventory.add_argument("--root", required=True)
    inventory.add_argument("--category", action="append", dest="categories")
    run = subparsers.add_parser("run", help="fit and score one image with pretrained WideResNet50-2")
    run.add_argument("--root", required=True)
    run.add_argument("--category", required=True)
    run.add_argument("--image", required=True)
    run.add_argument("--memory-bank-size", type=int, default=10_000)
    run.add_argument("--device", default="cpu")
    run.add_argument("--batch-size", type=int, default=8)
    args = parser.parse_args()
    if args.command == "inventory":
        report = discover_mvtec(args.root, args.categories)
        payload = {
            "root": str(report.root),
            "categories": list(report.categories),
            "files": len(report.files),
            "train_files": len(report.train_files),
            "issues": [{"kind": issue.kind, "path": str(issue.path), "detail": issue.detail, "category": issue.category} for issue in report.issues],
            "duplicate_groups": len(report.duplicate_hashes),
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if report.is_valid else 2
    if args.command == "run":
        report = discover_mvtec(args.root, [args.category])
        if not report.is_valid:
            print(json.dumps({"error": "dataset validation failed", "issues": [issue.detail for issue in report.issues]}))
            return 2
        from .runtime import WideResNetPatchCore

        runtime = WideResNetPatchCore(PatchCoreConfig(memory_bank_size=args.memory_bank_size), device=args.device, batch_size=args.batch_size)
        bank = runtime.fit(report.train_files)
        result = runtime.score(args.image)
        print(json.dumps({"category": args.category, "image": str(result.image), "score": result.score, "grid_shape": result.grid_shape, "memory_bank_rows": len(bank), "backbone": "torchvision WideResNet50-2 DEFAULT"}, indent=2, sort_keys=True))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
