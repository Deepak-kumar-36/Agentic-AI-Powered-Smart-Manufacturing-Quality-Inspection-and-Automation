"""Local HTTP API for the software-only inspection path.

The API supports an explicitly injected image scorer and policy map. Without
those dependencies it persists UNVERIFIED rather than accepting client-supplied
scores or decisions.
"""

from __future__ import annotations

from dataclasses import asdict
import base64
from io import BytesIO
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping, Protocol
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4
from datetime import datetime, timezone
from threading import RLock

from PIL import Image
import numpy as np

from .persistence import InspectionRecord, InspectionStore
from .camera import CameraError, FramePolicy, FreshFrameSelector, MjpegCameraSource, redact_camera_url, validate_camera_url
from .policy import DecisionPolicy, InspectionInput, ModelEvidence, reason_values


class ImageScorer(Protocol):
    def score(self, category: str, image: str | Path) -> Any: ...


class MetadataProvider(Protocol):
    def __call__(self) -> Mapping[str, Any]: ...


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


REVIEW_OUTCOMES = frozenset({"CONFIRMED_NORMAL", "CONFIRMED_DEFECT", "INCONCLUSIVE"})
DEFECT_TYPES = frozenset({"scratch", "dent", "crack", "contamination", "misalignment", "other"})
MAX_REVIEW_NOTE_LENGTH = 2000


def _record_payload(record: InspectionRecord) -> dict[str, Any]:
    payload = asdict(record)
    payload["reason_codes"] = list(record.reason_codes)
    payload["evidence"] = record.evidence
    return payload


def _public_metadata(value: Any) -> Any:
    """Keep provider output JSON-safe and free of locations or credentials."""
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            name = str(key).lower()
            if any(token in name for token in ("path", "secret", "password", "token", "credential", "api_key")):
                continue
            result[str(key)] = _public_metadata(item)
        return result
    if isinstance(value, list):
        return [_public_metadata(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, str) and (value.startswith("/") or value.startswith("~")):
            return None
        return value
    return None


class InspectionApi:
    def __init__(
        self,
        store: InspectionStore | None = None,
        *,
        model: ImageScorer | None = None,
        policies: Mapping[str, DecisionPolicy] | None = None,
        image_root: str | Path | None = None,
        metadata_provider: MetadataProvider | None = None,
        camera_source_factory: Any | None = None,
    ) -> None:
        self.store = store or InspectionStore()
        self.model = model
        self.policies = dict(policies or {})
        self.image_root = Path(image_root).resolve() if image_root is not None else None
        self.metadata_provider = metadata_provider
        self._camera_lock = RLock()
        self._camera_source_factory = camera_source_factory or MjpegCameraSource
        self._camera_source: Any | None = None
        self._camera_url: str | None = None
        self._camera_selector = FreshFrameSelector(FramePolicy(max_age_ms=1000))

    def reload_model(self, category: str | None = None) -> list[str]:
        """Invalidate the injected model cache after reviewed artifact replacement."""
        reload_fn = getattr(self.model, "reload", None)
        if not callable(reload_fn):
            raise RuntimeError("configured model does not support reload")
        return sorted(reload_fn(category))

    def handle(self, method: str, path: str, body: bytes = b"", headers: dict[str, str] | None = None) -> tuple[int, dict[str, Any]]:
        headers = {key.lower(): value for key, value in (headers or {}).items()}
        parsed = urlsplit(path)
        route = parsed.path.rstrip("/") or "/"
        try:
            if method == "GET" and route == "/health/live":
                return 200, {"status": "ok", "service": "inspection-api"}
            if method == "GET" and route == "/health/ready":
                return 200, {"ready": True, "components": {"database": "ready", "model": "ready" if self.model else "not_ready", "camera": self._camera_state(), "controller": "disabled"}}
            if method == "GET" and route == "/api/v1/system/status":
                return 200, {"mode": "software_only", "actuation_enabled": False, "model": "ready" if self.model else "not_ready", "camera": self._camera_state(), "database": "ready"}
            if method == "GET" and route == "/api/v1/camera/status":
                return 200, self._camera_status()
            if method == "POST" and route == "/api/v1/camera/configure":
                return self._configure_camera(body)
            if method == "POST" and route == "/api/v1/camera/capture-inspection":
                return self._capture_inspection(body, headers)
            if method == "GET" and route == "/api/v1/system/metadata":
                return self._metadata()
            if method == "GET" and route == "/api/v1/review-analytics":
                return self._review_analytics(parsed.query)
            if method == "POST" and route == "/api/v1/images":
                return self._upload_image(body)
            if method == "GET" and route == "/api/v1/inspections":
                limit = int(parse_qs(parsed.query).get("limit", [50])[0])
                return 200, {"items": [_record_payload(item) for item in self.store.list(limit)]}
            if method == "POST" and route == "/api/v1/inspections":
                return self._create(body, headers)
            if method in {"GET", "POST"} and route.startswith("/api/v1/inspections/"):
                segments = route.split("/")
                if len(segments) == 5 and segments[-1] == "events":
                    raise ApiError(404, "NOT_FOUND", "inspection was not found")
                inspection_id = segments[4]
                if method == "GET" and len(segments) == 6 and segments[5] == "reviews":
                    return 200, {"items": [asdict(review) for review in self.store.reviews(inspection_id)]}
                if method == "GET" and len(segments) == 6 and segments[5] == "events":
                    return 200, {"items": self.store.events(inspection_id)}
                if method == "POST" and len(segments) == 6 and segments[5] == "reviews":
                    return self._create_review(inspection_id, body)
                return 200, _record_payload(self.store.get(inspection_id))
            raise ApiError(404, "NOT_FOUND", "route was not found")
        except ApiError:
            raise
        except KeyError as exc:
            raise ApiError(404, "INSPECTION_NOT_FOUND", str(exc.args[0])) from exc
        except (ValueError, json.JSONDecodeError) as exc:
            raise ApiError(400, "INVALID_REQUEST", str(exc)) from exc

    def _metadata(self) -> tuple[int, dict[str, Any]]:
        if self.metadata_provider is None:
            return 200, {"available": False, "reason": "METADATA_NOT_CONFIGURED"}
        try:
            metadata = self.metadata_provider()
        except Exception:
            return 200, {"available": False, "reason": "METADATA_UNAVAILABLE"}
        if not isinstance(metadata, Mapping):
            return 200, {"available": False, "reason": "METADATA_INVALID"}
        return 200, {**_public_metadata(metadata), "available": True}

    def _review_analytics(self, query: str) -> tuple[int, dict[str, Any]]:
        values = parse_qs(query)
        def one(name: str) -> str | None:
            value = values.get(name, [None])[0]
            return value if value not in {None, ""} else None
        try:
            page = int(one("page") or 1)
            page_size = int(one("page_size") or 25)
            analytics = self.store.review_analytics(page=page, page_size=page_size, review_outcome=one("review_outcome"), ai_outcome=one("ai_outcome"), comparison=one("comparison"), review_state=one("review_state"))
        except ValueError as exc:
            raise ApiError(400, "INVALID_REVIEW_ANALYTICS_QUERY", str(exc)) from exc
        return 200, asdict(analytics)

    def _create_review(self, inspection_id: str, body: bytes) -> tuple[int, dict[str, Any]]:
        if len(body) > 16 * 1024:
            raise ApiError(413, "REQUEST_TOO_LARGE", "review request exceeds 16 KiB")
        try:
            payload = json.loads(body.decode("utf-8")) if body else {}
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ApiError(400, "INVALID_JSON", "review request must be JSON") from exc
        if not isinstance(payload, dict):
            raise ApiError(400, "INVALID_JSON", "review request must be a JSON object")
        outcome = payload.get("outcome")
        if outcome not in REVIEW_OUTCOMES:
            raise ApiError(400, "INVALID_REVIEW_OUTCOME", "outcome must be CONFIRMED_NORMAL, CONFIRMED_DEFECT, or INCONCLUSIVE")
        defect_type = payload.get("defect_type")
        if defect_type is not None and (outcome != "CONFIRMED_DEFECT" or defect_type not in DEFECT_TYPES):
            raise ApiError(400, "INVALID_DEFECT_TYPE", "defect_type is only supported for CONFIRMED_DEFECT and must be a supported value")
        note = payload.get("note")
        if note is not None and (not isinstance(note, str) or len(note) > MAX_REVIEW_NOTE_LENGTH):
            raise ApiError(400, "INVALID_REVIEW_NOTE", f"note must be text of at most {MAX_REVIEW_NOTE_LENGTH} characters")
        try:
            review = self.store.add_review(inspection_id, outcome=outcome, defect_type=defect_type, note=note.strip() if isinstance(note, str) and note.strip() else None)
        except KeyError as exc:
            raise ApiError(404, "INSPECTION_NOT_FOUND", str(exc.args[0])) from exc
        return 201, asdict(review)

    def _camera_state(self) -> str:
        with self._camera_lock:
            return "ready" if self._camera_source is not None else "not_configured"

    def _camera_status(self) -> dict[str, Any]:
        with self._camera_lock:
            if self._camera_source is None:
                return {"configured": False, "status": "not_configured", "url": None, "health": None}
            health = self._camera_source.health()
            return {"configured": True, "status": "ready" if health.get("open") and not health.get("last_error") else "error", "url": redact_camera_url(self._camera_url or ""), "health": health}

    def _configure_camera(self, body: bytes) -> tuple[int, dict[str, Any]]:
        if len(body) > 8 * 1024:
            raise ApiError(413, "REQUEST_TOO_LARGE", "camera configuration exceeds 8 KiB")
        try:
            payload = json.loads(body.decode("utf-8"))
            url = validate_camera_url(payload.get("url", ""))
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError, TypeError, ValueError) as exc:
            raise ApiError(400, "INVALID_CAMERA_URL", str(exc)) from exc
        try:
            source = self._camera_source_factory(url)
            source.open()
        except Exception as exc:
            if "source" in locals():
                source.close()
            raise ApiError(502, "CAMERA_UNAVAILABLE", "phone camera stream could not be opened") from exc
        with self._camera_lock:
            if self._camera_source is not None:
                self._camera_source.close()
            self._camera_source, self._camera_url = source, url
            self._camera_selector.reset()
        return 200, self._camera_status()

    def _capture_inspection(self, body: bytes, headers: dict[str, str]) -> tuple[int, dict[str, Any]]:
        if len(body) > 8 * 1024:
            raise ApiError(413, "REQUEST_TOO_LARGE", "capture request exceeds 8 KiB")
        try:
            payload = json.loads(body.decode("utf-8")) if body else {}
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ApiError(400, "INVALID_JSON", "capture request must be JSON") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("category"), str) or not payload["category"].strip():
            raise ApiError(400, "CATEGORY_REQUIRED", "category is required")
        idempotency_key = headers.get("idempotency-key")
        if not idempotency_key:
            raise ApiError(400, "IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key header is required")
        request = {"category": payload["category"].strip(), "source": "phone-camera"}
        record = self.store.create(idempotency_key, request)
        if record.outcome is not None:
            return 200, _record_payload(record)
        with self._camera_lock:
            source = self._camera_source
            if source is None:
                record = self.store.record_decision(record.inspection_id, outcome="UNVERIFIED", reason_codes=["CAMERA_NOT_CONFIGURED"], policy_version="policy-unverified", model_version=None, score=None)
                return 200, _record_payload(record)
            try:
                frame = source.read(5000)
                if frame is None:
                    raise CameraError("camera frame unavailable")
                accepted = self._camera_selector.accept(frame, now=datetime.now(timezone.utc))
                if self.image_root is None:
                    raise CameraError("image root is not configured")
                image_path = self.image_root / f"phone-camera-{uuid4().hex}.png"
                image_buffer = BytesIO()
                Image.fromarray(accepted.frame, mode="RGB").save(image_buffer, format="PNG")
                image_path.write_bytes(image_buffer.getvalue())
                record = self._decide(record.inspection_id, {"category": request["category"], "image_path": image_path.name}, evidence_extra={"input_image_data": "data:image/png;base64," + base64.b64encode(image_buffer.getvalue()).decode("ascii")})
            except (CameraError, OSError, ValueError):
                record = self.store.record_decision(record.inspection_id, outcome="UNVERIFIED", reason_codes=["CAMERA_FRAME_INVALID"], policy_version="policy-unverified", model_version=None, score=None)
        return 200, _record_payload(record)

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
            record = self._decide(record.inspection_id, payload)
        return 201, _record_payload(record)

    def _upload_image(self, body: bytes) -> tuple[int, dict[str, Any]]:
        if self.image_root is None:
            raise ApiError(503, "IMAGE_ROOT_NOT_CONFIGURED", "image upload requires a configured image root")
        if len(body) > 12 * 1024 * 1024:
            raise ApiError(413, "UPLOAD_TOO_LARGE", "uploaded image request exceeds 12 MiB")
        try:
            payload = json.loads(body.decode("utf-8"))
            filename = payload["filename"]
            encoded = payload["data_base64"]
            if not isinstance(filename, str) or not isinstance(encoded, str):
                raise ValueError("filename and data_base64 are required")
            raw = base64.b64decode(encoded, validate=True)
            with Image.open(BytesIO(raw)) as image:
                image.verify()
        except (KeyError, TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError, OSError) as exc:
            raise ApiError(400, "INVALID_IMAGE_UPLOAD", "filename and valid base64 image data are required") from exc
        suffix = Path(filename).suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".ppm"}:
            suffix = ".png"
        stored_name = f"dashboard-{uuid4().hex}{suffix}"
        target = self.image_root / stored_name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        return 201, {"image_path": stored_name, "bytes": len(raw)}

    def _decide(self, inspection_id: str, payload: dict[str, Any], *, evidence_extra: dict[str, Any] | None = None) -> InspectionRecord:
        category = payload["category"].strip()
        if self.model is None:
            return self.store.record_decision(
                inspection_id, outcome="UNVERIFIED", reason_codes=["MODEL_NOT_READY"],
                policy_version="policy-unverified", model_version=None, score=None,
            )
        policy = self.policies.get(category)
        if policy is None:
            return self.store.record_decision(
                inspection_id, outcome="UNVERIFIED", reason_codes=["UNSUPPORTED_CATEGORY"],
                policy_version="policy-unverified", model_version=None, score=None,
            )
        image_path = self._image_path(payload.get("image_path"))
        if image_path is None:
            return self.store.record_decision(
                inspection_id, outcome="UNVERIFIED", reason_codes=["IMAGE_INVALID"],
                policy_version=policy.version, model_version=None, score=None,
            )
        try:
            evidence = self.model.score(category, image_path)
        except Exception:
            return self.store.record_decision(
                inspection_id, outcome="UNVERIFIED", reason_codes=["MODEL_NOT_READY"],
                policy_version=policy.version, model_version=None, score=None,
            )
        decision = policy.evaluate(
            InspectionInput(valid=True),
            ModelEvidence(model_version=evidence.model_version, score=evidence.score),
        )
        evidence_payload: dict[str, Any] = dict(evidence_extra or {})
        heatmap = getattr(evidence, "heatmap", None)
        if heatmap is not None and self.image_root is not None:
            values = np.asarray(heatmap, dtype=np.float32)
            if values.size and np.isfinite(values).all():
                normalized = values - values.min()
                maximum = float(normalized.max())
                if maximum > 0:
                    normalized = normalized / maximum
                image_buffer = BytesIO()
                Image.fromarray(np.uint8(np.clip(normalized, 0, 1) * 255), mode="L").save(image_buffer, format="PNG")
                evidence_payload["heatmap_url"] = "data:image/png;base64," + base64.b64encode(image_buffer.getvalue()).decode("ascii")
        return self.store.record_decision(
            inspection_id,
            outcome=decision.outcome.value,
            reason_codes=reason_values(decision.reason_codes),
            policy_version=decision.policy_version,
            model_version=decision.model_version,
            score=decision.score,
            evidence=evidence_payload,
        )

    def _image_path(self, value: Any) -> Path | None:
        if not isinstance(value, str) or not value.strip():
            return None
        candidate = Path(value)
        if self.image_root is not None:
            candidate = (self.image_root / candidate).resolve() if not candidate.is_absolute() else candidate.resolve()
            try:
                candidate.relative_to(self.image_root)
            except ValueError:
                return None
        else:
            candidate = candidate.resolve()
        return candidate if candidate.is_file() else None


class _Handler(BaseHTTPRequestHandler):
    api: InspectionApi

    def _respond(self, status: int, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        # The local dashboard is intentionally served by a separate static
        # server during development. Keep the API browser-callable without
        # changing its routes or trusting any client-side decision fields.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Idempotency-Key")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
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

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Idempotency-Key")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def log_message(self, _format: str, *_args: object) -> None:
        return


def serve(
    host: str = "127.0.0.1",
    port: int = 8000,
    store: InspectionStore | None = None,
    *,
    model: ImageScorer | None = None,
    policies: Mapping[str, DecisionPolicy] | None = None,
    image_root: str | Path | None = None,
    metadata_provider: MetadataProvider | None = None,
) -> None:
    api = InspectionApi(store, model=model, policies=policies, image_root=image_root, metadata_provider=metadata_provider)
    serve_api(api, host=host, port=port)


def serve_api(api: InspectionApi, *, host: str = "127.0.0.1", port: int = 8000) -> None:
    """Serve an already configured API instance."""
    server = create_server(api, host=host, port=port)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        api.store.close()


def create_server(api: InspectionApi, *, host: str = "127.0.0.1", port: int = 8000) -> ThreadingHTTPServer:
    """Create a server for tests or callers that manage their own thread."""

    class Handler(_Handler):
        pass

    Handler.api = api
    return ThreadingHTTPServer((host, port), Handler)
