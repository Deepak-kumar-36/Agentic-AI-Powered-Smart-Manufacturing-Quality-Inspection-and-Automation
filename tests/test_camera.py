from datetime import datetime, timedelta, timezone
from io import BytesIO
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from app.camera import CameraError, CameraFrame, FramePolicy, FreshFrameSelector, MjpegCameraSource, extract_jpeg, validate_camera_url, validate_frame


def frame(sequence: int = 1, *, captured: datetime | None = None, shape=(64, 64, 3)) -> CameraFrame:
    image = np.zeros(shape, dtype=np.uint8)
    return CameraFrame(image, (captured or datetime.now(timezone.utc)).isoformat(), "camera-1", sequence, shape[1], shape[0])


class CameraTests(unittest.TestCase):
    def test_mjpeg_stream_reads_available_sub_chunk_jpeg_without_waiting_for_eof(self) -> None:
        image = BytesIO()
        Image.fromarray(np.zeros((64, 64, 3), dtype=np.uint8)).save(image, format="JPEG")

        class StreamingResponse:
            def __init__(self, payload):
                self.payload = payload
                self.fp = SimpleNamespace(raw=SimpleNamespace(_sock=SimpleNamespace(settimeout=lambda _value: None)))
                self.headers = {"Content-Type": "multipart/x-mixed-replace; boundary=frame"}
                self.status = 200
                self.closed = False

            def getcode(self):
                return self.status

            def close(self):
                self.closed = True

            def read(self, _size):
                raise TimeoutError("read(amt) waited for the full chunk")

            def read1(self, _size):
                chunk, self.payload = self.payload, b""
                return chunk

        source = MjpegCameraSource("http://127.0.0.1:8080/video")
        response = StreamingResponse(b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + image.getvalue() + b"\r\n")
        with patch("app.camera._NO_REDIRECT_OPENER.open", return_value=response):
            source.open()
        frame = source.read(5000)
        self.assertIsNotNone(frame)
        self.assertEqual((frame.width, frame.height), (64, 64))
        self.assertEqual(source.health()["frames_read"], 1)
        self.assertEqual(source.health()["http_status"], 200)
        self.assertTrue(source.health()["content_type"].startswith("multipart/x-mixed-replace"))

    def test_mjpeg_rejects_html_and_finite_http_responses_during_configuration(self) -> None:
        class Response:
            status = 200
            fp = SimpleNamespace(raw=SimpleNamespace(_sock=SimpleNamespace(settimeout=lambda _value: None)))

            def __init__(self, content_type, content_length=None):
                self.headers = {"Content-Type": content_type}
                if content_length is not None:
                    self.headers["Content-Length"] = str(content_length)
                self.closed = False

            def getcode(self):
                return self.status

            def close(self):
                self.closed = True

        for content_type, content_length, message in (
            ("text/html; charset=utf-8", None, "not multipart MJPEG"),
            ("multipart/x-mixed-replace; boundary=frame", 42, "finite response"),
        ):
            response = Response(content_type, content_length)
            source = MjpegCameraSource("http://127.0.0.1:8080")
            with patch("app.camera._NO_REDIRECT_OPENER.open", return_value=response):
                with self.assertRaisesRegex(CameraError, message):
                    source.open()
            self.assertTrue(response.closed)
            self.assertIsNone(source._response)

    def test_mjpeg_stream_timeout_and_eof_return_no_frame_with_diagnostics(self) -> None:
        class Response:
            def __init__(self, chunk):
                self.chunk = chunk
                self.fp = SimpleNamespace(raw=SimpleNamespace(_sock=SimpleNamespace(settimeout=lambda _value: None)))
                self.headers = {"Content-Type": "multipart/x-mixed-replace; boundary=frame"}

            def getcode(self):
                return 200

            def close(self):
                self.fp = None

            def read1(self, _size):
                if isinstance(self.chunk, Exception):
                    raise self.chunk
                chunk, self.chunk = self.chunk, b""
                if not chunk:
                    self.fp = None
                return chunk

            def read(self, _size):
                return self.read1(_size)

        for chunk, expected in ((b"", "phone camera stream ended"), (TimeoutError("timed out"), "phone camera read failed: timed out")):
            source = MjpegCameraSource("http://127.0.0.1:8080/video")
            source._response = Response(chunk)
            self.assertIsNone(source.read(5000))
            self.assertEqual(source.health()["last_error"], expected)
            if not chunk:
                self.assertIsNone(source._response)

    def test_read_after_eof_reopens_instead_of_using_closed_http_response(self) -> None:
        class Response:
            def __init__(self):
                self.headers = {"Content-Type": "multipart/x-mixed-replace; boundary=frame"}
                self.fp = SimpleNamespace(raw=SimpleNamespace(_sock=SimpleNamespace(settimeout=lambda _value: None)))

            def getcode(self):
                return 200

            def read1(self, _size):
                self.fp = None
                return b""

            def close(self):
                self.fp = None

        source = MjpegCameraSource("http://127.0.0.1:8080/video")
        with patch("app.camera._NO_REDIRECT_OPENER.open", side_effect=[Response(), Response()]) as open_stream:
            self.assertIsNone(source.read(5000))
            self.assertIsNone(source.read(5000))
        self.assertEqual(open_stream.call_count, 2)
        self.assertEqual(source.health()["last_error"], "phone camera stream ended")

    def test_extract_jpeg_handles_split_mjpeg_chunks(self) -> None:
        buffer = bytearray(b"noise\xff\xd8first")
        self.assertIsNone(extract_jpeg(buffer))
        buffer.extend(b"second\xff\xd9trailing")
        self.assertEqual(extract_jpeg(buffer), b"\xff\xd8firstsecond\xff\xd9")

    def test_phone_camera_requires_absolute_http_url(self) -> None:
        with self.assertRaises(ValueError):
            MjpegCameraSource("phone-camera/video")

    def test_phone_camera_rejects_credentials_and_public_hosts(self) -> None:
        with self.assertRaises(ValueError):
            validate_camera_url("http://user:password@127.0.0.1:8080/video")
        with self.assertRaises(ValueError):
            validate_camera_url("https://example.com/video")

    def test_valid_frame_is_accepted(self) -> None:
        accepted = FreshFrameSelector().accept(frame(), now=datetime.now(timezone.utc))
        self.assertEqual(accepted.sequence_no, 1)

    def test_stale_frame_is_rejected(self) -> None:
        old = datetime.now(timezone.utc) - timedelta(seconds=2)
        with self.assertRaisesRegex(CameraError, "stale"):
            validate_frame(frame(captured=old), FramePolicy(max_age_ms=500), now=datetime.now(timezone.utc))

    def test_replayed_sequence_is_rejected(self) -> None:
        selector = FreshFrameSelector()
        now = datetime.now(timezone.utc)
        selector.accept(frame(2, captured=now), now=now)
        with self.assertRaisesRegex(CameraError, "sequence"):
            selector.accept(frame(2, captured=now), now=now)

    def test_metadata_dimension_mismatch_is_rejected(self) -> None:
        value = frame()
        invalid = CameraFrame(value.frame, value.captured_at_utc, value.camera_id, value.sequence_no, 32, 32)
        with self.assertRaisesRegex(CameraError, "dimensions"):
            validate_frame(invalid, FramePolicy(), now=datetime.now(timezone.utc))

    def test_reset_allows_reconnected_camera_sequence(self) -> None:
        selector = FreshFrameSelector()
        now = datetime.now(timezone.utc)
        selector.accept(frame(4, captured=now), now=now)
        selector.reset("camera-1")
        self.assertEqual(selector.accept(frame(1, captured=now), now=now).sequence_no, 1)


if __name__ == "__main__":
    unittest.main()
