"""Explicit, experimental Gemini image assessment; never an inspection decision."""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
import threading
import time
from typing import Any, Protocol

from PIL import Image
from io import BytesIO

ASSESSMENTS = {"LIKELY_NORMAL", "POSSIBLE_DEFECT", "INCONCLUSIVE"}
DEFECT_TYPES = {"scratch", "dent", "crack", "contamination", "misalignment", "other", "unknown"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024
PROMPT = """Visually assess this manufacturing inspection image for demonstration only. Describe only visible, evidence-supported features. Distinguish direct observations from hypotheses. Report apparent scratches, dents, cracks, contamination, misalignment, or other relevant visible defects only when justified. Return INCONCLUSIVE when unclear or evidence is insufficient. State uncertainty and image-quality limitations; do not guess. Do not provide a production decision or probability. Return JSON with assessment (LIKELY_NORMAL, POSSIBLE_DEFECT, INCONCLUSIVE), defect_type (scratch, dent, crack, contamination, misalignment, other, unknown), observations (array of concise strings), limitations (array of strings)."""


class VisionError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


class VisionProvider(Protocol):
    def assess(self, image: bytes, mime_type: str) -> Any: ...


@dataclass
class GeminiProvider:
    api_key: str
    model: str
    timeout_seconds: int = 20
    client: Any = None

    def __post_init__(self) -> None:
        if self.client is None:
            try:
                from google import genai
                from google.genai import types
            except ImportError as exc:
                raise VisionError("VISION_SDK_UNAVAILABLE", "Install the optional google-genai package to enable vision assessment") from exc
            self.client = genai.Client(api_key=self.api_key, http_options=types.HttpOptions(timeout=self.timeout_seconds * 1000))

    def assess(self, image: bytes, mime_type: str) -> Any:
        from google.genai import types
        response = self.client.models.generate_content(
            model=self.model,
            contents=[PROMPT, types.Part.from_bytes(data=image, mime_type=mime_type)],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema={"type": "OBJECT", "properties": {
                    "assessment": {"type": "STRING", "enum": sorted(ASSESSMENTS)},
                    "defect_type": {"type": "STRING", "enum": sorted(DEFECT_TYPES)},
                    "observations": {"type": "ARRAY", "items": {"type": "STRING"}},
                    "limitations": {"type": "ARRAY", "items": {"type": "STRING"}},
                }, "required": ["assessment", "defect_type", "observations", "limitations"]},
                temperature=0,
                max_output_tokens=512,
                automatic_continuation=False,
            ),
        )
        return response.text


def validate_assessment(value: Any, model: str) -> dict[str, Any]:
    try:
        data = json.loads(value) if isinstance(value, str) else value
    except (json.JSONDecodeError, TypeError) as exc:
        raise VisionError("VISION_INVALID_RESPONSE", "Provider returned malformed JSON") from exc
    if not isinstance(data, dict) or data.get("assessment") not in ASSESSMENTS or data.get("defect_type") not in DEFECT_TYPES:
        raise VisionError("VISION_INVALID_RESPONSE", "Provider response has unsupported assessment or defect category")
    for key in ("observations", "limitations"):
        if not isinstance(data.get(key), list) or len(data[key]) > 12 or any(not isinstance(v, str) or len(v) > 500 for v in data[key]):
            raise VisionError("VISION_INVALID_RESPONSE", f"Provider response has invalid {key}")
    return {"assessment": data["assessment"], "defect_type": data["defect_type"], "observations": data["observations"], "limitations": data["limitations"], "provider": "gemini", "model": model, "evaluation_mode": "DEMO_ADVISORY", "qualified": False}


class VisionAssessmentService:
    def __init__(self, enabled: bool | None = None, api_key: str | None = None, model: str | None = None, timeout: int | None = None, provider: VisionProvider | None = None):
        self.enabled = (os.getenv("VISION_API_ENABLED", "false").lower() == "true") if enabled is None else enabled
        self.api_key = api_key if api_key is not None else os.getenv("GEMINI_API_KEY", "")
        self.model = model or os.getenv("VISION_API_MODEL", "gemini-flash-latest")
        try:
            configured_timeout = timeout if timeout is not None else int(os.getenv("VISION_API_TIMEOUT_SECONDS", "20"))
        except ValueError:
            configured_timeout = 20
        self.timeout = max(1, min(configured_timeout, 60))
        self.provider = provider
        self._lock = threading.Lock()
        self._last_request: dict[str, float] = {}

    def assess(self, inspection_id: str, image: bytes, mime_type: str) -> dict[str, Any]:
        if not self.enabled:
            raise VisionError("VISION_DISABLED", "Experimental vision assessment is disabled")
        if not self.api_key and self.provider is None:
            raise VisionError("VISION_CREDENTIALS_MISSING", "GEMINI_API_KEY is required when vision assessment is enabled")
        if not image or len(image) > MAX_IMAGE_BYTES:
            raise VisionError("INVALID_EVIDENCE", "Image evidence is empty or exceeds 10 MiB")
        try:
            with Image.open(BytesIO(image)) as decoded:
                decoded.verify()
                mime_type = Image.MIME.get(decoded.format, mime_type)
        except Exception as exc:
            raise VisionError("INVALID_EVIDENCE", "Managed image evidence is invalid") from exc
        now = time.monotonic()
        with self._lock:
            # Keep the throttle state bounded if the store contains many IDs.
            self._last_request = {key: stamp for key, stamp in self._last_request.items() if now - stamp < 60}
            if now - self._last_request.get(inspection_id, 0) < 10:
                raise VisionError("VISION_RATE_LIMITED", "Wait 10 seconds before requesting another assessment for this inspection")
            self._last_request[inspection_id] = now
        if self.provider is None:
            try:
                self.provider = GeminiProvider(self.api_key, self.model, self.timeout)
            except VisionError:
                raise
            except Exception as exc:
                raise VisionError("VISION_PROVIDER_ERROR", "Gemini provider could not be initialized") from exc
        try:
            result = self.provider.assess(image, mime_type)
        except TimeoutError as exc:
            raise VisionError("VISION_TIMEOUT", "Gemini assessment timed out") from exc
        except Exception as exc:
            status = getattr(exc, "code", None) or getattr(exc, "status_code", None)
            code = "VISION_RATE_LIMITED" if status == 429 or str(status).upper() in {"RESOURCE_EXHAUSTED", "TOO_MANY_REQUESTS"} else "VISION_TIMEOUT" if status == 504 or "timeout" in str(exc).lower() else "VISION_PROVIDER_ERROR"
            message = "Gemini rate limit or quota was reached" if code == "VISION_RATE_LIMITED" else "Gemini assessment timed out" if code == "VISION_TIMEOUT" else "Gemini assessment failed"
            raise VisionError(code, message) from exc
        return validate_assessment(result, self.model)
