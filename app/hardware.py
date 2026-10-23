"""Optional, fail-safe USB-serial bridge for the ESP32 indicator firmware."""

from __future__ import annotations

from dataclasses import dataclass
import json
from threading import Event, Lock, Thread
import time
from typing import Any, Callable, Protocol
from uuid import uuid4

from .structured_logging import logger


PROTOCOL_VERSION = 1
MAX_LINE_BYTES = 1024
VALID_DECISIONS = frozenset({"PASS", "FAIL", "UNVERIFIED"})


class SerialTransport(Protocol):
    def write(self, data: bytes) -> int: ...
    def readline(self) -> bytes: ...
    def close(self) -> None: ...


def _message(payload: dict[str, Any]) -> bytes:
    return (json.dumps({"schema_version": PROTOCOL_VERSION, **payload}, separators=(",", ":")) + "\n").encode("utf-8")


def _bounded_json(raw: bytes) -> dict[str, Any] | None:
    if not raw or len(raw) > MAX_LINE_BYTES or not raw.endswith(b"\n"):
        return None
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) and value.get("schema_version") == PROTOCOL_VERSION else None


@dataclass(frozen=True)
class HardwareSnapshot:
    enabled: bool
    state: str
    last_error: str | None
    last_command_id: str | None
    last_command_state: str | None
    last_decision: str | None
    indicator: str
    sensor_active: bool | None
    sensor_updated_at: float | None
    firmware_version: str | None


class DisabledHardware:
    def snapshot(self) -> HardwareSnapshot:
        return HardwareSnapshot(False, "disabled", None, None, None, None, "off", None, None, None)

    def send_decision(self, _inspection_id: str, _decision: str) -> None:
        return

    def close(self) -> None:
        return


class Esp32Bridge:
    """Bounded serial bridge; transport failures never affect persisted inspections."""

    def __init__(
        self,
        transport: SerialTransport,
        *,
        read_timeout_s: float = 0.2,
        stale_after_s: float = 5.0,
        heartbeat_interval_s: float = 1.0,
        reconnect_factory: Callable[[], SerialTransport] | None = None,
        reconnect_interval_s: float = 1.0,
    ) -> None:
        self._transport = transport
        self._read_timeout_s = read_timeout_s
        self._stale_after_s = stale_after_s
        self._heartbeat_interval_s = heartbeat_interval_s
        self._reconnect_factory = reconnect_factory
        self._reconnect_interval_s = reconnect_interval_s
        self._lock = Lock()
        self._write_lock = Lock()
        self._stop = Event()
        self._snapshot = HardwareSnapshot(True, "connected", None, None, None, None, "off", None, None, None)
        self._reader_thread: Thread | None = None
        self._heartbeat_thread = Thread(target=self._heartbeat_worker, name="esp32-heartbeat", daemon=True)
        self._reconnect_thread = Thread(target=self._reconnect_worker, name="esp32-serial-reconnect", daemon=True)
        self._start_reader(transport)
        self._heartbeat_thread.start()
        if self._reconnect_factory is not None:
            self._reconnect_thread.start()

    def _start_reader(self, transport: SerialTransport) -> None:
        self._reader_thread = Thread(target=self._reader, args=(transport,), name="esp32-serial-reader", daemon=True)
        self._reader_thread.start()

    def _write_line(self, payload: dict[str, Any]) -> None:
        raw = _message(payload)
        with self._write_lock:
            self._transport.write(raw)

    def _send_heartbeat(self) -> None:
        self._write_line({"type": "heartbeat"})

    def _heartbeat_worker(self) -> None:
        # Emit an immediate initial heartbeat to refresh link state and trigger controller.status
        try:
            self._send_heartbeat()
        except Exception:
            pass

        while not self._stop.is_set():
            if self._stop.wait(self._heartbeat_interval_s):
                break
            with self._lock:
                is_connected = self._snapshot.state != "disconnected"
            if not is_connected:
                continue
            try:
                self._send_heartbeat()
            except Exception as exc:
                with self._lock:
                    old = self._snapshot
                    self._snapshot = HardwareSnapshot(
                        True, "disconnected", str(exc),
                        old.last_command_id, old.last_command_state,
                        old.last_decision, "off",
                        old.sensor_active, old.sensor_updated_at,
                        old.firmware_version,
                    )

    def _reader(self, transport: SerialTransport) -> None:
        while not self._stop.is_set():
            try:
                raw = transport.readline()
            except Exception as exc:
                with self._lock:
                    if transport is not self._transport:
                        return
                    old = self._snapshot
                    self._snapshot = HardwareSnapshot(
                        True, "disconnected", str(exc),
                        old.last_command_id, old.last_command_state,
                        old.last_decision, "off",
                        old.sensor_active, old.sensor_updated_at,
                        old.firmware_version,
                    )
                return
            if not raw:
                continue
            message = _bounded_json(raw)
            if message is None:
                with self._lock:
                    old = self._snapshot
                    self._snapshot = HardwareSnapshot(
                        True, "connected", "malformed firmware message",
                        old.last_command_id, old.last_command_state,
                        old.last_decision, old.indicator,
                        old.sensor_active, old.sensor_updated_at,
                        old.firmware_version,
                    )
                continue
            self._accept(message)

    def _reconnect_worker(self) -> None:
        """Reopen only the configured serial device after a transport failure."""
        while not self._stop.wait(self._reconnect_interval_s):
            with self._lock:
                should_reconnect = self._snapshot.state == "disconnected"
            if not should_reconnect or self._reconnect_factory is None:
                continue
            try:
                self.reconnect(self._reconnect_factory())
                logger.info("hardware.reconnect.completed")
            except Exception as exc:
                with self._lock:
                    old = self._snapshot
                    self._snapshot = HardwareSnapshot(
                        True, "disconnected", f"serial reconnect failed: {type(exc).__name__}",
                        old.last_command_id, old.last_command_state, old.last_decision, "off",
                        old.sensor_active, old.sensor_updated_at, old.firmware_version,
                    )

    def _accept(self, message: dict[str, Any]) -> None:
        now = time.time()
        kind = message.get("type")
        with self._lock:
            old = self._snapshot
            if kind == "command.ack":
                cmd_id = message.get("command_id")
                if not isinstance(cmd_id, str) or not cmd_id:
                    self._snapshot = HardwareSnapshot(
                        True, "connected", "command.ack missing command_id",
                        old.last_command_id, old.last_command_state, old.last_decision,
                        old.indicator, old.sensor_active, old.sensor_updated_at, old.firmware_version,
                    )
                    return
                # Older command acknowledgments or mismatched IDs must NEVER confirm a newer or different command
                if cmd_id != old.last_command_id:
                    return

                ok = (message.get("ok") is True) or (message.get("status") == "ACCEPTED" and not message.get("error_code"))
                if ok:
                    # Successfully acknowledged: only now update the confirmed indicator state
                    confirmed_indicator = "off"
                    if old.last_decision == "PASS":
                        confirmed_indicator = "pass"
                    elif old.last_decision == "FAIL":
                        confirmed_indicator = "fail"
                    self._snapshot = HardwareSnapshot(
                        True, "connected", None,
                        cmd_id, "acknowledged", old.last_decision,
                        confirmed_indicator, old.sensor_active, old.sensor_updated_at, old.firmware_version,
                    )
                    logger.info("hardware.command.ack_received", command_id=cmd_id, status="accepted", indicator=confirmed_indicator)
                else:
                    err = str(message.get("error_code") or message.get("status") or "command rejected")
                    self._snapshot = HardwareSnapshot(
                        True, "connected", err,
                        cmd_id, "rejected", old.last_decision,
                        "off", old.sensor_active, old.sensor_updated_at, old.firmware_version,
                    )
                    logger.warning("hardware.command.ack_received", command_id=cmd_id, status="rejected", error=err)

            elif kind == "error":
                cmd_id = message.get("command_id")
                err = str(message.get("error_code") or "firmware error")
                if isinstance(cmd_id, str) and cmd_id == old.last_command_id:
                    self._snapshot = HardwareSnapshot(
                        True, "connected", err,
                        cmd_id, "rejected", old.last_decision,
                        "off", old.sensor_active, old.sensor_updated_at, old.firmware_version,
                    )
                else:
                    self._snapshot = HardwareSnapshot(
                        True, "connected", err,
                        old.last_command_id, old.last_command_state, old.last_decision,
                        old.indicator, old.sensor_active, old.sensor_updated_at, old.firmware_version,
                    )

            elif kind in {"sensor.state", "sensor.status"}:
                sensor_active = message.get("sensor_active")
                if not isinstance(sensor_active, bool):
                    sensor_active = message.get("active")
                if isinstance(sensor_active, bool):
                    self._snapshot = HardwareSnapshot(
                        True, "connected", old.last_error,
                        old.last_command_id, old.last_command_state, old.last_decision,
                        old.indicator, sensor_active, now, old.firmware_version,
                    )

            elif kind in {"hello", "controller.status"}:
                fw = str(message.get("firmware_version") or old.firmware_version or "unknown")
                sensor_active = message.get("sensor_active")
                if not isinstance(sensor_active, bool):
                    sensor_active = message.get("active")
                s_active = sensor_active if isinstance(sensor_active, bool) else old.sensor_active
                s_time = now if isinstance(sensor_active, bool) else old.sensor_updated_at
                firmware_stale = message.get("state") == "STALE" or message.get("link_stale") is True
                self._snapshot = HardwareSnapshot(
                    True, "stale" if firmware_stale else "connected", "firmware link stale" if firmware_stale else old.last_error,
                    old.last_command_id, old.last_command_state, old.last_decision,
                    "off" if firmware_stale else old.indicator, s_active, s_time, fw,
                )

    def send_decision(self, inspection_id: str, decision: str) -> None:
        if decision not in VALID_DECISIONS:
            raise ValueError("invalid hardware decision")
        command_id = uuid4().hex
        try:
            self._write_line({
                "type": "inspection.disposition",
                "command_id": command_id,
                "inspection_id": inspection_id,
                "decision": decision,
            })
        except Exception as exc:
            with self._lock:
                old = self._snapshot
                self._snapshot = HardwareSnapshot(
                    True, "disconnected", str(exc),
                    command_id, "write_failed", decision,
                    "off", old.sensor_active, old.sensor_updated_at, old.firmware_version,
                )
            logger.warning("hardware.command.write_failed", inspection_id=inspection_id, command_id=command_id, error=str(exc))
            return
        with self._lock:
            old = self._snapshot
            # Delivery remains unconfirmed until a valid matching ACK arrives. Do NOT update indicator optimistically.
            self._snapshot = HardwareSnapshot(
                True, "connected", None,
                command_id, "sent_unconfirmed", decision,
                old.indicator, old.sensor_active, old.sensor_updated_at, old.firmware_version,
            )
        logger.info("hardware.command.sent", inspection_id=inspection_id, outcome=decision, command_id=command_id)

    def reconnect(self, new_transport: SerialTransport) -> None:
        """Safely attach a new transport upon reconnection."""
        with self._lock:
            with self._write_lock:
                old_transport = self._transport
                self._transport = new_transport
            self._snapshot = HardwareSnapshot(
                True, "connected", None,
                self._snapshot.last_command_id, self._snapshot.last_command_state,
                self._snapshot.last_decision, "off",
                self._snapshot.sensor_active, self._snapshot.sensor_updated_at,
                self._snapshot.firmware_version,
            )
        try:
            old_transport.close()
        except Exception:
            pass
        self._start_reader(new_transport)
        if not self._heartbeat_thread.is_alive():
            self._heartbeat_thread = Thread(target=self._heartbeat_worker, name="esp32-heartbeat", daemon=True)
            self._heartbeat_thread.start()
        else:
            try:
                self._send_heartbeat()
            except Exception:
                pass

    def snapshot(self) -> HardwareSnapshot:
        with self._lock:
            current = self._snapshot
        if current.state == "disconnected":
            return current
        if current.state == "stale":
            return HardwareSnapshot(
                current.enabled, "stale", current.last_error or "sensor data stale",
                current.last_command_id, current.last_command_state, current.last_decision,
                "off", current.sensor_active, current.sensor_updated_at, current.firmware_version,
            )
        if current.sensor_updated_at is not None and time.time() - current.sensor_updated_at > self._stale_after_s:
            return HardwareSnapshot(
                current.enabled, "stale", "sensor data stale",
                current.last_command_id, current.last_command_state, current.last_decision,
                "off", current.sensor_active, current.sensor_updated_at, current.firmware_version,
            )
        return current

    def close(self) -> None:
        self._stop.set()
        try:
            with self._write_lock:
                self._transport.close()
        finally:
            if self._reader_thread is not None and self._reader_thread.is_alive():
                self._reader_thread.join(timeout=1)
            if self._heartbeat_thread.is_alive():
                self._heartbeat_thread.join(timeout=1)
            if self._reconnect_factory is not None and self._reconnect_thread.is_alive():
                self._reconnect_thread.join(timeout=1)


def open_serial_bridge(port: str, baudrate: int = 115200, *, heartbeat_interval_s: float = 1.0) -> Esp32Bridge:
    try:
        import serial  # type: ignore
    except ImportError as exc:
        raise RuntimeError("hardware support requires optional dependency pyserial") from exc
    def connect() -> SerialTransport:
        # POSIX exclusive mode prevents another process from opening the same
        # tty while the supervised bridge owns it.
        return serial.Serial(port=port, baudrate=baudrate, timeout=0.2, write_timeout=0.5, exclusive=True)

    return Esp32Bridge(connect(), heartbeat_interval_s=heartbeat_interval_s, reconnect_factory=connect)
