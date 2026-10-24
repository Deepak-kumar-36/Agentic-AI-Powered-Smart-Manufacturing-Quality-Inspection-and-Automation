import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import time
import unittest

import numpy as np

from app.api import InspectionApi
from app.hardware import HardwareSnapshot
from app.persistence import InspectionStore
from app.policy import DecisionPolicy


class Evidence:
    model_version = "efficientad-s-native-v1"

    def __init__(self, score: float = 0.1) -> None:
        self.score = score


class Model:
    def score(self, _category, _image):
        return Evidence()


class FailingModel:
    def score(self, _category, _image):
        raise RuntimeError("model unavailable")


class FreshCamera:
    def __init__(self) -> None:
        self.opened = False
        self.reads = 0

    def open(self) -> None:
        self.opened = True

    def close(self) -> None:
        self.opened = False

    def health(self):
        return {"camera_id": "fake", "open": self.opened, "last_error": None}

    def read(self, _timeout_ms):
        self.reads += 1
        return type("Frame", (), {
            "frame": np.zeros((64, 64, 3), dtype=np.uint8),
            "captured_at_utc": datetime.now(timezone.utc).isoformat(),
            "camera_id": "fake",
            "sequence_no": self.reads,
            "width": 64,
            "height": 64,
        })()


class SensorHardware:
    def __init__(self) -> None:
        self.listener = None
        self.decisions = []
        self.current = HardwareSnapshot(True, "connected", None, None, None, None, "off", None, None, "test")

    def set_sensor_listener(self, listener) -> None:
        self.listener = listener

    def snapshot(self):
        return self.current

    def send_decision(self, inspection_id, decision) -> None:
        self.decisions.append((inspection_id, decision))

    def emit(self, active, *, state="connected", timestamp=None) -> None:
        self.current = HardwareSnapshot(True, state, None, None, None, None, "off", active, time.time() if timestamp is None else timestamp, "test")
        if self.listener is not None:
            self.listener(self.current)

    def close(self) -> None:
        return


def wait_for(predicate, timeout=1.5) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


class AutoCaptureTests(unittest.TestCase):
    def make_api(self, directory, hardware, camera):
        api = InspectionApi(
            InspectionStore(),
            model=Model(),
            policies={"bottle": DecisionPolicy("policy-1", frozenset({"efficientad-s-native-v1"}), 0.2, 0.8)},
            image_root=directory,
            camera_source_factory=lambda _url: camera,
            hardware=hardware,
            auto_capture_on_ir=True,
            auto_capture_category="bottle",
        )
        api.handle("POST", "/api/v1/camera/configure", json.dumps({"url": "http://127.0.0.1:8080/video"}).encode())
        return api

    def close_api(self, api):
        api.close()
        api.store.close()

    def test_rising_edge_captures_once_after_debounce_and_rearms_only_after_clear(self):
        with tempfile.TemporaryDirectory() as directory:
            hardware, camera = SensorHardware(), FreshCamera()
            api = self.make_api(directory, hardware, camera)
            try:
                hardware.emit(True)  # Initial state is baseline, not a rising edge.
                time.sleep(0.25)
                self.assertEqual(api.store.list(10), [])
                hardware.emit(False)
                hardware.emit(True)
                hardware.emit(True)  # Periodic telemetry cannot duplicate the capture.
                self.assertTrue(wait_for(lambda: len(api.store.list(10)) == 1 and api.store.list(10)[0].outcome is not None))
                self.assertEqual(camera.reads, 1)
                self.assertEqual(api.store.list(10)[0].outcome, "PASS")
                self.assertEqual(len(hardware.decisions), 1)
                time.sleep(0.25)
                self.assertEqual(len(api.store.list(10)), 1)
                hardware.emit(False)
                hardware.emit(True)
                self.assertTrue(wait_for(lambda: len(api.store.list(10)) == 2))
                self.assertEqual(camera.reads, 2)
            finally:
                self.close_api(api)

    def test_clear_during_debounce_cancels_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            hardware, camera = SensorHardware(), FreshCamera()
            api = self.make_api(directory, hardware, camera)
            try:
                hardware.emit(False)
                hardware.emit(True)
                hardware.emit(False)
                time.sleep(0.25)
                self.assertEqual(api.store.list(10), [])
                self.assertEqual(camera.reads, 0)
                self.assertEqual(hardware.decisions, [])
            finally:
                self.close_api(api)

    def test_stale_disconnected_or_unavailable_camera_never_creates_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            hardware, camera = SensorHardware(), FreshCamera()
            api = InspectionApi(
                InspectionStore(), model=Model(),
                policies={"bottle": DecisionPolicy("policy-1", frozenset({"efficientad-s-native-v1"}), 0.2, 0.8)},
                image_root=directory, camera_source_factory=lambda _url: camera,
                hardware=hardware, auto_capture_on_ir=True, auto_capture_category="bottle",
            )
            try:
                hardware.emit(False)
                hardware.emit(True)  # Camera is not configured.
                time.sleep(0.25)
                self.assertEqual(api.store.list(10), [])
                self.assertEqual(camera.reads, 0)
                hardware.emit(False, state="stale")
                hardware.emit(True, state="stale")
                hardware.emit(False, state="connected", timestamp=time.time() - 10)
                hardware.emit(True, state="disconnected")
                time.sleep(0.25)
                self.assertEqual(api.store.list(10), [])
            finally:
                self.close_api(api)

    def test_manual_capture_still_uses_existing_path_when_auto_capture_enabled(self):
        with tempfile.TemporaryDirectory() as directory:
            hardware, camera = SensorHardware(), FreshCamera()
            api = self.make_api(directory, hardware, camera)
            try:
                status, record = api.handle(
                    "POST", "/api/v1/camera/capture-inspection",
                    b'{"category":"bottle"}', {"Idempotency-Key": "manual-still-works"},
                )
                self.assertEqual(status, 200)
                self.assertEqual(record["outcome"], "PASS")
                self.assertEqual(camera.reads, 1)
                self.assertEqual(hardware.decisions, [(record["inspection_id"], "PASS")])
            finally:
                self.close_api(api)

    def test_inference_failure_stays_unverified_and_consumes_the_sensor_arm(self):
        with tempfile.TemporaryDirectory() as directory:
            hardware, camera = SensorHardware(), FreshCamera()
            api = InspectionApi(
                InspectionStore(), model=FailingModel(),
                policies={"bottle": DecisionPolicy("policy-1", frozenset({"efficientad-s-native-v1"}), 0.2, 0.8)},
                image_root=directory, camera_source_factory=lambda _url: camera,
                hardware=hardware, auto_capture_on_ir=True, auto_capture_category="bottle",
            )
            try:
                api.handle("POST", "/api/v1/camera/configure", b'{"url":"http://127.0.0.1:8080/video"}')
                hardware.emit(False)
                hardware.emit(True)
                self.assertTrue(wait_for(lambda: len(api.store.list(10)) == 1 and api.store.list(10)[0].outcome is not None))
                record = api.store.list(10)[0]
                self.assertEqual(record.outcome, "UNVERIFIED")
                self.assertEqual(record.reason_codes, ("MODEL_NOT_READY",))
                self.assertEqual(hardware.decisions, [(record.inspection_id, "UNVERIFIED")])
                hardware.emit(True)
                time.sleep(0.25)
                self.assertEqual(len(api.store.list(10)), 1)
            finally:
                self.close_api(api)

    def test_auto_capture_requires_real_bridge_and_configured_category(self):
        policy = {"bottle": DecisionPolicy("policy-1", frozenset({"efficientad-s-native-v1"}), 0.2, 0.8)}
        store = InspectionStore()
        try:
            with self.assertRaisesRegex(ValueError, "ESP32 hardware bridge"):
                InspectionApi(store, policies=policy, auto_capture_on_ir=True, auto_capture_category="bottle")
        finally:
            store.close()
        hardware = SensorHardware()
        store = InspectionStore()
        try:
            with self.assertRaisesRegex(ValueError, "AUTO_CAPTURE_CATEGORY"):
                InspectionApi(store, hardware=hardware, policies=policy, auto_capture_on_ir=True, auto_capture_category="unknown")
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
