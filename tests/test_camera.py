from datetime import datetime, timedelta, timezone
import unittest

import numpy as np

from app.camera import CameraError, CameraFrame, FramePolicy, FreshFrameSelector, MjpegCameraSource, extract_jpeg, validate_camera_url, validate_frame


def frame(sequence: int = 1, *, captured: datetime | None = None, shape=(64, 64, 3)) -> CameraFrame:
    image = np.zeros(shape, dtype=np.uint8)
    return CameraFrame(image, (captured or datetime.now(timezone.utc)).isoformat(), "camera-1", sequence, shape[1], shape[0])


class CameraTests(unittest.TestCase):
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
