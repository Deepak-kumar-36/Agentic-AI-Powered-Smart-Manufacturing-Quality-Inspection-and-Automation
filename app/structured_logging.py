"""Structured JSON logging and correlation context for the inspection runtime.

Follows Document 14 and Document 12 specifications:
- One structured JSON object per line.
- Mandatory common fields: timestamp, level, event, service, service_version, boot_id.
- Context propagation: request_id, correlation_id, inspection_id via contextvars.
- Redaction of credentials, auth tokens, secrets, URLs with passwords, and raw image data.
"""

from __future__ import annotations

from contextvars import ContextVar
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
import re
import sys
import threading
from typing import Any, Callable, Generator, Mapping, Sequence
from uuid import uuid4

SERVICE_NAME = "inspection-api"
SERVICE_VERSION = "0.1.0"
BOOT_ID = f"boot-{uuid4().hex[:12]}"

# Context variables for distributed/request tracing
_REQUEST_ID_VAR: ContextVar[str | None] = ContextVar("request_id", default=None)
_CORRELATION_ID_VAR: ContextVar[str | None] = ContextVar("correlation_id", default=None)
_INSPECTION_ID_VAR: ContextVar[str | None] = ContextVar("inspection_id", default=None)

# Redaction patterns and sensitive key identifiers
_SENSITIVE_KEY_TOKENS = frozenset({
    "password", "passwd", "secret", "token", "api_key", "apikey",
    "authorization", "cookie", "credential", "private_key",
})

_IMAGE_DATA_KEY_TOKENS = frozenset({
    "data_base64", "input_image_data", "raw_image", "image_bytes",
    "frame_data", "image_data",
})

_CREDENTIAL_URL_PATTERN = re.compile(r"^(https?://)([^:@/]+):([^@/]+)@(.*)$", re.IGNORECASE)


def redact_url(url: str) -> str:
    """Scrub username and password from URL string."""
    match = _CREDENTIAL_URL_PATTERN.match(url)
    if match:
        scheme, _user, _pass, rest = match.groups()
        return f"{scheme}***:***@{rest}"
    return url


def redact_value(key: str | None, value: Any) -> Any:
    """Recursively scrub sensitive fields, credentials, and image bytes."""
    lower_key = str(key).lower() if key is not None else ""

    if any(token in lower_key for token in _SENSITIVE_KEY_TOKENS):
        return "[REDACTED]"

    if any(token in lower_key for token in _IMAGE_DATA_KEY_TOKENS):
        if isinstance(value, str):
            return f"[REDACTED_IMAGE_DATA: {len(value)} chars]"
        if isinstance(value, (bytes, bytearray)):
            return f"[REDACTED_IMAGE_DATA: {len(value)} bytes]"
        return "[REDACTED_IMAGE_DATA]"

    if isinstance(value, (bytes, bytearray)):
        return f"[REDACTED_BYTES: {len(value)} bytes]"

    if isinstance(value, str):
        if value.startswith("data:image/"):
            return f"[REDACTED_IMAGE_DATA: {len(value)} chars]"
        if _CREDENTIAL_URL_PATTERN.match(value):
            return redact_url(value)
        return value

    if isinstance(value, Mapping):
        return {str(k): redact_value(k, v) for k, v in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [redact_value(None, item) for item in value]

    if isinstance(value, (int, float, bool)) or value is None:
        return value

    # Non-primitive fallback: stringify safely
    return str(value)


def get_request_id() -> str | None:
    return _REQUEST_ID_VAR.get()


def get_correlation_id() -> str | None:
    return _CORRELATION_ID_VAR.get()


def get_inspection_id() -> str | None:
    return _INSPECTION_ID_VAR.get()


@contextmanager
def correlation_context(
    request_id: str | None = None,
    correlation_id: str | None = None,
    inspection_id: str | None = None,
) -> Generator[dict[str, str | None], None, None]:
    """Scoped context manager for binding correlation IDs."""
    req_token = _REQUEST_ID_VAR.set(request_id)
    corr_token = _CORRELATION_ID_VAR.set(correlation_id)
    insp_token = _INSPECTION_ID_VAR.set(inspection_id)
    try:
        yield {
            "request_id": _REQUEST_ID_VAR.get(),
            "correlation_id": _CORRELATION_ID_VAR.get(),
            "inspection_id": _INSPECTION_ID_VAR.get(),
        }
    finally:
        _REQUEST_ID_VAR.reset(req_token)
        _CORRELATION_ID_VAR.reset(corr_token)
        _INSPECTION_ID_VAR.reset(insp_token)


def set_inspection_id(inspection_id: str | None) -> None:
    """Update current inspection ID in context."""
    _INSPECTION_ID_VAR.set(inspection_id)


def clear_correlation_context() -> None:
    """Explicitly reset all correlation variables."""
    _REQUEST_ID_VAR.set(None)
    _CORRELATION_ID_VAR.set(None)
    _INSPECTION_ID_VAR.set(None)



# Global sink for capturing logs in tests
_TEST_SINKS: list[list[dict[str, Any]]] = []
_SINK_LOCK = threading.RLock()


@contextmanager
def capture_logs() -> Generator[list[dict[str, Any]], None, None]:
    """Capture structured log events in memory during test execution."""
    sink: list[dict[str, Any]] = []
    with _SINK_LOCK:
        _TEST_SINKS.append(sink)
    try:
        yield sink
    finally:
        with _SINK_LOCK:
            if sink in _TEST_SINKS:
                _TEST_SINKS.remove(sink)


class StructuredLogger:
    """Thread-safe JSON logger adhering to Document 14."""

    LEVELS = {
        "DEBUG": 10,
        "INFO": 20,
        "WARNING": 30,
        "ERROR": 40,
        "CRITICAL": 50,
    }

    def __init__(
        self,
        service: str = SERVICE_NAME,
        version: str = SERVICE_VERSION,
        stream: Any = None,
    ) -> None:
        self.service = service
        self.version = version
        self.stream = stream or sys.stderr
        self._lock = threading.RLock()
        self._min_level = self.LEVELS.get(
            os.getenv("LOG_LEVEL", "INFO").upper(),
            20,
        )

    def set_level(self, level: str) -> None:
        self._min_level = self.LEVELS.get(level.upper(), 20)

    def log(self, level: str, event: str, **fields: Any) -> dict[str, Any]:
        level_upper = level.upper()
        level_num = self.LEVELS.get(level_upper, 20)
        if level_num < self._min_level:
            return {}

        now_iso = datetime.now(timezone.utc).isoformat()
        
        # Build core record
        record: dict[str, Any] = {
            "timestamp": now_iso,
            "level": level_upper,
            "event": event,
            "service": self.service,
            "service_version": self.version,
            "boot_id": BOOT_ID,
        }

        # Add correlation context if present
        req_id = fields.pop("request_id", None) or _REQUEST_ID_VAR.get()
        corr_id = fields.pop("correlation_id", None) or _CORRELATION_ID_VAR.get()
        insp_id = fields.pop("inspection_id", None) or _INSPECTION_ID_VAR.get()

        if req_id is not None:
            record["request_id"] = str(req_id)
        if corr_id is not None:
            record["correlation_id"] = str(corr_id)
        if insp_id is not None:
            record["inspection_id"] = str(insp_id)

        # Redact remaining fields
        redacted_fields = redact_value(None, fields)
        if isinstance(redacted_fields, dict):
            record.update(redacted_fields)

        # Emit to sinks (tests) and stream
        with _SINK_LOCK:
            for sink in _TEST_SINKS:
                sink.append(dict(record))

        line = json.dumps(record, separators=(",", ":"))
        with self._lock:
            try:
                self.stream.write(line + "\n")
                self.stream.flush()
            except Exception:
                pass

        return record

    def debug(self, event: str, **fields: Any) -> dict[str, Any]:
        return self.log("DEBUG", event, **fields)

    def info(self, event: str, **fields: Any) -> dict[str, Any]:
        return self.log("INFO", event, **fields)

    def warning(self, event: str, **fields: Any) -> dict[str, Any]:
        return self.log("WARNING", event, **fields)

    def error(self, event: str, **fields: Any) -> dict[str, Any]:
        return self.log("ERROR", event, **fields)

    def critical(self, event: str, **fields: Any) -> dict[str, Any]:
        return self.log("CRITICAL", event, **fields)


# Module-level default logger instance
logger = StructuredLogger()
