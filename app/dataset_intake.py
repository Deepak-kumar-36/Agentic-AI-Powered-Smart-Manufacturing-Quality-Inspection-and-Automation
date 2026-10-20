"""Validate reviewed-evidence packages and stage isolated, unapproved candidates."""

from __future__ import annotations

import argparse
import ctypes
from dataclasses import fields
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import uuid
import zipfile

from .dataset_package import PackageLimits, validate_package


_CHUNK = 64 * 1024
_ALLOWED = {"VALID", "VALID_WITH_WARNINGS"}


def _json(value: dict) -> str:
    return json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n"


def _copy(source, target, cap: int) -> tuple[int, str]:
    """Copy at most cap bytes; reject excess without writing it."""
    size = 0
    digest = hashlib.sha256()
    while raw := source.read(min(_CHUNK, cap - size + 1)):
        size += len(raw)
        if size > cap:
            raise ValueError("Stream exceeds its byte limit.")
        target.write(raw)
        digest.update(raw)
    return size, digest.hexdigest()


def _digest(path: Path, cap: int) -> str:
    class Sink:
        def write(self, raw):
            return len(raw)

    with path.open("rb") as source:
        return _copy(source, Sink(), cap)[1]


def _publish(root_fd: int, temporary: str, destination: str) -> None:
    # Linux renameat2 provides atomic publication AND no replacement (including
    # an existing empty directory). A check followed by Path.rename cannot.
    rename = ctypes.CDLL(None, use_errno=True).renameat2
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(root_fd, os.fsencode(temporary), root_fd, os.fsencode(destination), 1):
        raise OSError(ctypes.get_errno(), "Candidate publication failed.")


def stage_package(path: str | Path, staging_root: str | Path, limits: PackageLimits | None = None) -> dict:
    """Return {destination: generated basename or None, report: validation report}.

    Invalid input never creates a candidate. Operational failures raise; the
    caller receives no source path in error messages emitted by the CLI.
    """
    limits = limits or PackageLimits()
    with tempfile.TemporaryDirectory(prefix="dataset-snapshot-") as scratch:
        snapshot = Path(scratch) / "package.zip"
        # Keep one extra byte so the validator can report an oversized package,
        # while never copying an unbounded source (including a growing file).
        with Path(path).open("rb") as source, snapshot.open("xb") as target:
            remaining = limits.max_compressed_bytes + 1
            while remaining:
                raw = source.read(min(_CHUNK, remaining))
                if not raw:
                    break
                target.write(raw)
                remaining -= len(raw)
        snapshot.chmod(0o400)
        report = validate_package(snapshot, limits)
        if report["status"] == "INVALID":
            return {"destination": None, "report": report}
        if report["status"] not in _ALLOWED or _digest(snapshot, limits.max_compressed_bytes) != report["source_sha256"]:
            raise ValueError("Snapshot validation binding failed.")

        root = Path(staging_root)
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Hold the root inode open: all subsequent work stays anchored even if
        # its pathname is concurrently renamed. Refuse a symlink root itself.
        root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        temporary = None
        try:
            anchored = Path(f"/proc/self/fd/{root_fd}")
            temporary = Path(tempfile.mkdtemp(prefix=".candidate-", dir=anchored))
            (temporary / "images").mkdir(mode=0o700)
            mapping = []
            total = 0
            with zipfile.ZipFile(snapshot) as archive:
                with archive.open("manifest.jsonl") as stream:
                    raw = stream.read(limits.max_metadata_bytes + 1)
                if len(raw) > limits.max_metadata_bytes:
                    raise ValueError("Manifest exceeds its byte limit.")
                rows = raw.decode("utf-8").splitlines()
                if len(rows) > limits.max_images:
                    raise ValueError("Manifest exceeds its record limit.")
                with (temporary / "manifest.jsonl").open("x", encoding="utf-8", newline="\n") as manifest:
                    for index, line in enumerate(rows, 1):
                        row = json.loads(line)
                        original = row["image_path"]
                        generated = f"images/{index:06d}{Path(original).suffix.lower()}"
                        with archive.open(original) as source, (temporary / generated).open("xb") as target:
                            size, digest = _copy(source, target, min(limits.max_image_bytes, limits.max_uncompressed_bytes - total))
                        total += size
                        if digest != row["input_image_sha256"]:
                            raise ValueError("Staged image digest mismatch.")
                        row["image_path"] = generated
                        manifest.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
                        mapping.append({"record_index": index, "source_image_path": original, "image_path": generated})
            metadata = {"source_sha256": report["source_sha256"], "validation_status": report["status"],
                        "candidate_only": True, "training_approved": False,
                        "source_manifest": "manifest.jsonl", "image_mapping": mapping}
            for name, value in (("staging-manifest.json", metadata), ("validation-report.json", report)):
                with (temporary / name).open("x", encoding="utf-8", newline="\n") as stream:
                    stream.write(_json(value))
            if _digest(snapshot, limits.max_compressed_bytes) != report["source_sha256"]:
                raise ValueError("Snapshot validation binding failed.")
            destination = "candidate-" + uuid.uuid4().hex
            _publish(root_fd, temporary.name, destination)
            temporary = None
            return {"destination": destination, "report": report}
        finally:
            if temporary is not None:
                shutil.rmtree(temporary)
            os.close(root_fd)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("validate", "stage"):
        child = commands.add_parser(command)
        child.add_argument("package", type=Path)
        child.add_argument("--report", type=Path)
        if command == "stage":
            child.add_argument("--staging-root", type=Path, required=True)
        for field in fields(PackageLimits):
            child.add_argument("--" + field.name.replace("_", "-"), type=float if field.name == "max_compression_ratio" else int)
    args = parser.parse_args(argv)
    report_file = None
    try:
        limits = PackageLimits(**{field.name: getattr(args, field.name) for field in fields(PackageLimits) if getattr(args, field.name) is not None})
        # Reserve the requested output before staging so an existing report
        # cannot result in a published candidate followed by a CLI failure.
        if args.report:
            report_file = args.report.open("x", encoding="utf-8", newline="\n")
        result = stage_package(args.package, args.staging_root, limits) if args.command == "stage" else validate_package(args.package, limits)
        report = result["report"] if args.command == "stage" else result
        serialized = _json(result)
        if report_file:
            report_file.write(serialized)
        sys.stdout.write(serialized)
        if any(item.get("code") == "SOURCE_UNREADABLE" for item in report["errors"]):
            return 2
        return 0 if report["status"] in _ALLOWED else 1
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile, AttributeError):
        sys.stderr.write("Dataset intake failed: invalid limits or an input/output operation failed.\n")
        return 2
    finally:
        if report_file:
            report_file.close()


if __name__ == "__main__":
    raise SystemExit(main())
