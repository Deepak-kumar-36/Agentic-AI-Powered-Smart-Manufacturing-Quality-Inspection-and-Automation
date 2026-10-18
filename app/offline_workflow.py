"""Offline capture-to-decision workflow using stored image frames."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from .api import InspectionApi
from .camera import CameraFrame, CameraError, FreshFrameSelector, FramePolicy


class FileFrameSource:
    """Read one image file through the existing camera frame contract."""

    def __init__(self, path: str | Path, *, camera_id: str = "offline-file") -> None:
        self.path = Path(path)
        self.camera_id = camera_id
        self._sequence = 0
        self._last_error: str | None = None

    def open(self) -> None:
        return

    def read(self, timeout_ms: int) -> CameraFrame | None:
        if timeout_ms < 1:
            raise ValueError("timeout_ms must be positive")
        try:
            with Image.open(self.path) as image:
                frame = np.asarray(image.convert("RGB"), dtype=np.uint8).copy()
        except Exception as exc:
            self._last_error = f"file image decode failed: {exc}"
            return None
        self._sequence += 1
        self._last_error = None
        return CameraFrame(
            frame=frame,
            captured_at_utc=datetime.now(timezone.utc).isoformat(),
            camera_id=self.camera_id,
            sequence_no=self._sequence,
            width=frame.shape[1],
            height=frame.shape[0],
        )

    def health(self) -> dict[str, Any]:
        return {
            "camera_id": self.camera_id,
            "transport": "file",
            "path_configured": bool(str(self.path)),
            "last_error": self._last_error,
        }

    def close(self) -> None:
        return


class OfflineInspectionWorkflow:
    """Capture one stored frame, persist it, and run the existing API path."""

    def __init__(
        self,
        api: InspectionApi,
        source: FileFrameSource,
        category: str,
        capture_root: str | Path,
        *,
        timeout_ms: int = 1000,
    ) -> None:
        if not category.strip():
            raise ValueError("category must not be empty")
        self.api = api
        self.source = source
        self.category = category.strip()
        self.capture_root = Path(capture_root).resolve()
        self.timeout_ms = timeout_ms
        self.selector = FreshFrameSelector(FramePolicy(min_width=1, min_height=1, max_age_ms=1000))

    def run(self, idempotency_key: str) -> dict[str, Any]:
        frame = self.source.read(self.timeout_ms)
        image_path: str | None = None
        if frame is not None:
            try:
                frame = self.selector.accept(frame)
            except CameraError:
                frame = None
        if frame is not None:
            self.capture_root.mkdir(parents=True, exist_ok=True)
            key = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()[:16]
            name = f"{self.source.path.stem}-{key}.png"
            target = self.capture_root / name
            Image.fromarray(frame.frame, mode="RGB").save(target, format="PNG")
            image_path = name
        payload = {"category": self.category, "source": "offline-file"}
        if image_path is not None:
            payload["image_path"] = image_path
        _, record = self.api.handle(
            "POST",
            "/api/v1/inspections",
            body=json.dumps(payload).encode("utf-8"),
            headers={"Idempotency-Key": idempotency_key},
        )
        return record
