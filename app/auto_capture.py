"""Opt-in, fail-closed IR rising-edge capture coordination."""

from __future__ import annotations

from threading import Lock, Thread, Timer
import time
from typing import Callable

from .hardware import HardwareSnapshot
from .structured_logging import logger


class IrAutoCaptureController:
    """Turn fresh clear-to-detected telemetry into one supervised capture.

    The ESP32 performs electrical debounce.  This controller adds a short
    host-side stability window, consumes one arm per clear transition, and
    deliberately never decides an inspection outcome.
    """

    def __init__(
        self,
        *,
        category: str,
        capture: Callable[[str], None],
        snapshot: Callable[[], HardwareSnapshot],
        debounce_s: float = 0.15,
        telemetry_max_age_s: float = 2.0,
    ) -> None:
        self.category = category
        self._capture = capture
        self._snapshot = snapshot
        self._debounce_s = debounce_s
        self._telemetry_max_age_s = telemetry_max_age_s
        self._lock = Lock()
        self._last_active: bool | None = None
        self._armed = False
        self._pending = False
        self._in_progress = False
        self._generation = 0
        self._timer: Timer | None = None
        self._closed = False

    def _fresh(self, snapshot: HardwareSnapshot) -> bool:
        return (
            snapshot.state == "connected"
            and isinstance(snapshot.sensor_active, bool)
            and isinstance(snapshot.sensor_updated_at, (int, float))
            and 0 <= time.time() - snapshot.sensor_updated_at <= self._telemetry_max_age_s
        )

    def on_sensor_snapshot(self, snapshot: HardwareSnapshot) -> None:
        """Accept a validated bridge snapshot without blocking the reader."""
        with self._lock:
            if self._closed:
                return
            if not self._fresh(snapshot):
                self._generation += 1
                self._last_active = None
                self._armed = False
                self._pending = False
                if self._timer is not None:
                    self._timer.cancel()
                    self._timer = None
                return

            active = snapshot.sensor_active
            if active is False:
                self._generation += 1
                self._last_active = False
                self._armed = True
                self._pending = False
                if self._timer is not None:
                    self._timer.cancel()
                    self._timer = None
                return

            # Establishing an initial state (including after reconnect) must
            # not manufacture a rising edge.
            if self._last_active is None:
                self._last_active = True
                return
            if self._last_active is True or not self._armed or self._pending or self._in_progress:
                self._last_active = True
                return

            self._last_active = True
            self._pending = True
            token = self._generation
            self._timer = Timer(self._debounce_s, self._after_debounce, args=(token,))
            self._timer.daemon = True
            self._timer.start()

    def _after_debounce(self, token: int) -> None:
        with self._lock:
            if self._closed:
                return
            current = self._snapshot()
            if token != self._generation or not self._fresh(current) or current.sensor_active is not True:
                self._pending = False
                return
            self._pending = False
            self._in_progress = True
            self._armed = False
        Thread(target=self._run_capture, name="ir-auto-capture", daemon=True).start()

    def _run_capture(self) -> None:
        try:
            self._capture(self.category)
        except Exception as exc:  # Capture errors must never affect serial processing.
            logger.error("auto_capture.failed", error_type=type(exc).__name__)
        finally:
            with self._lock:
                self._in_progress = False

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._generation += 1
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
