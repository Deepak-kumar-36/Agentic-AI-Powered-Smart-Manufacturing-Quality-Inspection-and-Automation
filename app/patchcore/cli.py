"""Small offline CLI for dataset inventory; benchmark commands stay explicit."""

from __future__ import annotations

import argparse
import json

from .dataset import discover_mvtec


def main() -> int:
    parser = argparse.ArgumentParser(prog="patchcore")
    subparsers = parser.add_subparsers(dest="command", required=True)
    inventory = subparsers.add_parser("inventory", help="validate and inventory an MVTec AD root")
    inventory.add_argument("--root", required=True)
    inventory.add_argument("--category", action="append", dest="categories")
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
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
