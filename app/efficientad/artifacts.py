from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: str | Path, payload: dict[str, Any]) -> None:
    destination = Path(path)
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_manifest(output_dir: str | Path, files: list[str], metadata: dict[str, Any]) -> Path:
    root = Path(output_dir)
    manifest = {"schema_version": "efficientad-artifact-manifest-v1", "metadata": metadata, "files": {name: sha256_file(root / name) for name in sorted(files)}}
    destination = root / "manifest.json"
    write_json(destination, manifest)
    return destination
