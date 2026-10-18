"""Hardware-neutral camera frame contract and stale-frame guard."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
import select
import subprocess
import time
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


class V4L2CameraSource:
    """Read bounded RGB frames from a Linux V4L2 device through ffmpeg.

    ffmpeg is intentionally kept outside the Python dependency graph. This makes
    the adapter usable with the existing project environment while keeping the
    transport-specific process isolated from model and policy code.
    """

    def __init__(
        self,
        device: str,
        *,
        width: int = 1280,
        height: int = 720,
        fps: int = 30,
        input_format: str = "mjpeg",
        ffmpeg_bin: str = "ffmpeg",
    ) -> None:
        if not device.startswith("/dev/video"):
            raise ValueError("V4L2 device must be under /dev/video")
        if min(width, height, fps) < 1:
            raise ValueError("camera dimensions and fps must be positive")
        self.device = device
        self.width = width
        self.height = height
        self.fps = fps
        self.input_format = input_format
        self.ffmpeg_bin = ffmpeg_bin
        self._process: subprocess.Popen[bytes] | None = None
        self._sequence = 0
        self._last_error: str | None = None
        self._frames_read = 0

    def open(self) -> None:
        if self._process is not None:
            return
        command = [
            self.ffmpeg_bin,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "v4l2",
            "-input_format",
            self.input_format,
            "-video_size",
            f"{self.width}x{self.height}",
            "-framerate",
            str(self.fps),
            "-i",
            self.device,
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "pipe:1",
        ]
        try:
            self._process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
        except OSError as exc:
            self._last_error = str(exc)
            raise CameraError(f"unable to open camera source: {exc}") from exc

    def read(self, timeout_ms: int) -> CameraFrame | None:
        if timeout_ms < 1:
            raise ValueError("timeout_ms must be positive")
        self.open()
        process = self._process
        if process is None or process.stdout is None:
            self._last_error = "camera process has no stdout"
            return None
        frame_bytes = self.width * self.height * 3
        deadline = time.monotonic() + timeout_ms / 1000
        chunks: list[bytes] = []
        remaining = frame_bytes
        while remaining:
            wait_seconds = deadline - time.monotonic()
            if wait_seconds <= 0:
                self._last_error = "camera read timed out"
                return None
            ready, _, _ = select.select([process.stdout], [], [], wait_seconds)
            if not ready:
                self._last_error = "camera read timed out"
                return None
            chunk = os.read(process.stdout.fileno(), remaining)
            if not chunk:
                self._last_error = "camera stream ended before a complete frame"
                return None
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if len(payload) != frame_bytes:
            self._last_error = "camera returned an incomplete frame"
            return None
        self._sequence += 1
        self._frames_read += 1
        self._last_error = None
        return CameraFrame(
            np.frombuffer(payload, dtype=np.uint8).reshape(self.height, self.width, 3),
            datetime.now(timezone.utc).isoformat(),
            self.device,
            self._sequence,
            self.width,
            self.height,
        )

    def health(self) -> dict[str, Any]:
        process = self._process
        return {
            "camera_id": self.device,
            "transport": "v4l2-ffmpeg",
            "configured": True,
            "open": process is not None and process.poll() is None,
            "frames_read": self._frames_read,
            "last_error": self._last_error,
        }

    def close(self) -> None:
        process, self._process = self._process, None
        if process is None:
            return
        process.terminate()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        time.sleep(0)
