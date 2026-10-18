"""Hardware-neutral camera frame contract and stale-frame guard."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

import numpy as np


class CameraError(RuntimeError):
    """Raised for invalid or unavailable camera frames."""


@dataclass(frozen=True)
class CameraFrame:
    frame: np.ndarray
    captured_at_utc: str
    camera_id: str
    sequence_no: int
    width: int
    height: int


class CameraSource(Protocol):
    def open(self) -> None: ...
    def read(self, timeout_ms: int) -> CameraFrame | None: ...
    def health(self) -> dict[str, Any]: ...
    def close(self) -> None: ...


@dataclass(frozen=True)
class FramePolicy:
    max_age_ms: int = 500
    min_width: int = 32
    min_height: int = 32
    channels: int = 3

    def __post_init__(self) -> None:
        if self.max_age_ms < 0 or self.min_width < 1 or self.min_height < 1 or self.channels not in {1, 3, 4}:
            raise ValueError("invalid camera frame policy")


def _parse_timestamp(value: str) -> datetime:
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CameraError("camera timestamp is invalid") from exc
    if timestamp.tzinfo is None:
        raise CameraError("camera timestamp must include a timezone")
    return timestamp.astimezone(timezone.utc)


def validate_frame(frame: CameraFrame, policy: FramePolicy, *, now: datetime | None = None) -> CameraFrame:
    """Validate dimensions, pixels, sequence identity, and freshness."""
    if not frame.camera_id.strip() or frame.sequence_no < 0:
        raise CameraError("camera identity or sequence number is invalid")
    if frame.width < policy.min_width or frame.height < policy.min_height:
        raise CameraError("camera frame dimensions are below the configured minimum")
    if not isinstance(frame.frame, np.ndarray) or frame.frame.ndim != 3:
        raise CameraError("camera frame must be a three-dimensional numpy array")
    if frame.frame.shape[1] != frame.width or frame.frame.shape[0] != frame.height:
        raise CameraError("camera metadata dimensions do not match frame dimensions")
    if frame.frame.shape[2] != policy.channels:
        raise CameraError("camera frame channel count is unsupported")
    if frame.frame.dtype != np.uint8 or not np.isfinite(frame.frame).all():
        raise CameraError("camera frame pixels must be finite uint8 values")
    captured = _parse_timestamp(frame.captured_at_utc)
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    age_ms = (current - captured).total_seconds() * 1000
    if age_ms < -50 or age_ms > policy.max_age_ms:
        raise CameraError("camera frame is stale or timestamped in the future")
    return frame


class FreshFrameSelector:
    """Reject stale/replayed frames while keeping only the newest accepted frame."""

    def __init__(self, policy: FramePolicy | None = None) -> None:
        self.policy = policy or FramePolicy()
        self._last_sequence: dict[str, int] = {}

    def accept(self, frame: CameraFrame, *, now: datetime | None = None) -> CameraFrame:
        validate_frame(frame, self.policy, now=now)
        previous = self._last_sequence.get(frame.camera_id)
        if previous is not None and frame.sequence_no <= previous:
            raise CameraError("camera frame sequence is stale or replayed")
        self._last_sequence[frame.camera_id] = frame.sequence_no
        return frame

    def reset(self, camera_id: str | None = None) -> None:
        if camera_id is None:
            self._last_sequence.clear()
        else:
            self._last_sequence.pop(camera_id, None)
