"""Dependency-free local HTTP API for the software-only inspection path.

The API intentionally has no model or hardware fallback. Until a qualified
PatchCore release and camera source are configured, an inspection is persisted
as UNVERIFIED rather than accepting client-supplied scores or decisions.
"""

from __future__ import annotations

from dataclasses import asdict
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

from .persistence import InspectionRecord, InspectionStore


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def _record_payload(record: InspectionRecord) -> dict[str, Any]:
    payload = asdict(record)
    payload["reason_codes"] = list(record.reason_codes)
    return payload


class InspectionApi:
    def __init__(self, store: InspectionStore | None = None) -> None:
        self.store = store or InspectionStore()

    def handle(self, method: str, path: str, body: bytes = b"", headers: dict[str, str] | None = None) -> tuple[int, dict[str, Any]]:
        headers = {key.lower(): value for key, value in (headers or {}).items()}
        parsed = urlsplit(path)
        route = parsed.path.rstrip("/") or "/"
        try:
            if method == "GET" and route == "/health/live":
                return 200, {"status": "ok", "service": "inspection-api"}
            if method == "GET" and route == "/health/ready":
                return 200, {"ready": True, "components": {"database": "ready", "model": "not_ready", "camera": "not_configured", "controller": "disabled"}}
            if method == "GET" and route == "/api/v1/system/status":
                return 200, {"mode": "software_only", "actuation_enabled": False, "model": "not_ready", "camera": "not_configured", "database": "ready"}
            if method == "GET" and route == "/api/v1/inspections":
                limit = int(parse_qs(parsed.query).get("limit", [50])[0])
                return 200, {"items": [_record_payload(item) for item in self.store.list(limit)]}
            if method == "POST" and route == "/api/v1/inspections":
                return self._create(body, headers)
            if method == "GET" and route.startswith("/api/v1/inspections/"):
                segments = route.split("/")
                if len(segments) == 5 and segments[-1] == "events":
                    raise ApiError(404, "NOT_FOUND", "inspection was not found")
                inspection_id = segments[4]
                if len(segments) == 6 and segments[5] == "events":
                    return 200, {"items": self.store.events(inspection_id)}
                return 200, _record_payload(self.store.get(inspection_id))
            raise ApiError(404, "NOT_FOUND", "route was not found")
        except ApiError:
            raise
        except KeyError as exc:
            raise ApiError(404, "INSPECTION_NOT_FOUND", str(exc.args[0])) from exc
        except (ValueError, json.JSONDecodeError) as exc:
            raise ApiError(400, "INVALID_REQUEST", str(exc)) from exc

    def _create(self, body: bytes, headers: dict[str, str]) -> tuple[int, dict[str, Any]]:
        if len(body) > 64 * 1024:
            raise ApiError(413, "REQUEST_TOO_LARGE", "request body exceeds 64 KiB")
        idempotency_key = headers.get("idempotency-key")
        if not idempotency_key:
            raise ApiError(400, "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key header is required")
        try:
            payload = json.loads(body.decode("utf-8")) if body else {}
        except UnicodeDecodeError as exc:
            raise ApiError(400, "INVALID_JSON", "request body is not UTF-8 JSON") from exc
        if not isinstance(payload, dict):
            raise ApiError(400, "INVALID_JSON", "request body must be a JSON object")
        if not isinstance(payload.get("category"), str) or not payload["category"].strip():
            raise ApiError(400, "CATEGORY_REQUIRED", "category is required")
        record = self.store.create(idempotency_key, payload)
        if record.outcome is None:
            record = self.store.record_decision(
                record.inspection_id,
                outcome="UNVERIFIED",
                reason_codes=["MODEL_NOT_READY"],
                policy_version="policy-unverified",
                model_version=None,
                score=None,
            )
        return 201, _record_payload(record)


class _Handler(BaseHTTPRequestHandler):
    api: InspectionApi

    def _respond(self, status: int, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _dispatch(self, method: str) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b""
        try:
            status, payload = self.api.handle(method, self.path, body, dict(self.headers.items()))
        except ApiError as exc:
            status, payload = exc.status, {"error": {"code": exc.code, "message": exc.message}}
        self._respond(status, payload)

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")

    def log_message(self, _format: str, *_args: object) -> None:
        return


def serve(host: str = "127.0.0.1", port: int = 8000, store: InspectionStore | None = None) -> None:
    api = InspectionApi(store)

    class Handler(_Handler):
        pass

    Handler.api = api
    server = ThreadingHTTPServer((host, port), Handler)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        api.store.close()
