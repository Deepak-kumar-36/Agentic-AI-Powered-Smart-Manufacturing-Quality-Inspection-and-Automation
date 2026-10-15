"""Safe, content-addressed PatchCore artifact writers."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np


def _refuse(path: Path) -> None:
    if path.exists():
        raise FileExistsError(f"refusing to overwrite existing artifact: {path}")


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: str | Path, metadata: dict[str, Any]) -> str:
    destination = Path(path)
    _refuse(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(metadata, sort_keys=True, indent=2, allow_nan=False).encode()
    destination.write_bytes(encoded)
    return _hash(destination)


def write_array(path: str | Path, array: Any) -> str:
    destination = Path(path)
    _refuse(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    values = np.asarray(array)
    if not np.all(np.isfinite(values)):
        raise ValueError("artifact arrays must contain only finite values")
    with destination.open("wb") as stream:
        np.save(stream, values, allow_pickle=False)
    return _hash(destination)


def write_release_manifest(path: str | Path, metadata: dict[str, Any], artifact_paths: list[str | Path]) -> str:
    """Write an immutable release manifest with hashes for referenced artifacts."""

    artifacts = []
    for artifact in artifact_paths:
        artifact_path = Path(artifact)
        if not artifact_path.is_file():
            raise FileNotFoundError(artifact_path)
        artifacts.append({"path": str(artifact_path), "sha256": _hash(artifact_path)})
    payload = {**metadata, "artifacts": artifacts}
    return write_json(path, payload)
