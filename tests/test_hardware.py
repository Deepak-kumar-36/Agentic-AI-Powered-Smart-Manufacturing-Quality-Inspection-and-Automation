from collections import deque
import json
from pathlib import Path
import re
import time
import unittest

from app.hardware import DisabledHardware, Esp32Bridge, MAX_LINE_BYTES, _bounded_json


class FakeTransport:
    def __init__(self):
        self.writes = []
        self.reads = deque()
        self.closed = False

    def write(self, data):
        self.writes.append(data)
        return len(data)

    def readline(self):
        return self.reads.popleft() if self.reads else b""

    def close(self):
        self.closed = True


class HardwareBridgeTests(unittest.TestCase):
    def test_firmware_source_pin_assignments_and_input_configuration(self):
        main_cpp = Path(__file__).resolve().parent.parent / "firmware" / "esp32_indicator_sensor" / "src" / "main.cpp"
        self.assertTrue(main_cpp.is_file(), f"main.cpp not found at {main_cpp}")
        content = main_cpp.read_text(encoding="utf-8")

        # Verify GPIO pins match physical breadboard wiring: Red=5, Green=4, IR=23
        self.assertRegex(content, r"constexpr\s+uint8_t\s+RED_LED_GPIO\s*=\s*5;")
        self.assertRegex(content, r"constexpr\s+uint8_t\s+GREEN_LED_GPIO\s*=\s*4;")
        self.assertRegex(content, r"constexpr\s+uint8_t\s+IR_SENSOR_GPIO\s*=\s*23;")

        # Verify active-low IR sensor and input pullup configuration
        self.assertRegex(content, r"constexpr\s+uint8_t\s+IR_SENSOR_ACTIVE_LEVEL\s*=\s*LOW;")
        self.assertIn("pinMode(IR_SENSOR_GPIO, INPUT_PULLUP);", content)
        self.assertIn("pinMode(RED_LED_GPIO, OUTPUT);", content)
        self.assertIn("pinMode(GREEN_LED_GPIO, OUTPUT);", content)

        # Verify command_id parsing in firmware source
        self.assertIn('readStringField(json, "command_id", commandId, sizeof(commandId))', content)
        self.assertIn('\\"command_id\\":\\"%s\\"', content)

    def test_protocol_rejects_malformed_oversized_and_wrong_version(self):
        self.assertIsNone(_bounded_json(b"bad\n"))
        self.assertIsNone(_bounded_json(b"{}\n"))
        self.assertIsNone(_bounded_json(b"x" * MAX_LINE_BYTES + b"\n"))
        self.assertIsNone(_bounded_json(b'{"schema_version":2,"type":"hello"}\n'))
        self.assertEqual(_bounded_json(b'{"schema_version":1,"type":"hello"}\n')["type"], "hello")

    def test_indicator_is_not_optimistically_updated_on_send(self):
        transport = FakeTransport()
        bridge = Esp32Bridge(transport)
        try:
            bridge.send_decision("ins-1", "PASS")
            snap = bridge.snapshot()
            # Must remain unconfirmed and indicator must NOT be optimistically set to pass
            self.assertEqual(snap.last_command_state, "sent_unconfirmed")
            self.assertEqual(snap.indicator, "off")
            self.assertEqual(snap.last_decision, "PASS")
        finally:
            bridge.close()

    def test_matching_acknowledgment_accepted_and_updates_indicator(self):
        transport = FakeTransport()
        bridge = Esp32Bridge(transport)
        try:
            bridge.send_decision("ins-1", "PASS")
            sent = json.loads(transport.writes[-1])
            self.assertEqual(sent["type"], "inspection.disposition")
            cmd_id = sent["command_id"]

            # Matching ACK
            ack_msg = json.dumps({
                "schema_version": 1,
                "type": "command.ack",
                "command_id": cmd_id,
                "inspection_id": "ins-1",
                "status": "ACCEPTED",
                "ok": True,
            }) + "\n"
            transport.reads.append(ack_msg.encode())
            transport.reads.append(b'{"schema_version":1,"type":"sensor.state","sensor_active":true}\n')

            deadline = time.time() + 1
            while time.time() < deadline and bridge.snapshot().last_command_state != "acknowledged":
                time.sleep(0.01)

            snapshot = bridge.snapshot()
            self.assertEqual(snapshot.last_command_state, "acknowledged")
            self.assertEqual(snapshot.indicator, "pass")
            self.assertTrue(snapshot.sensor_active)
            self.assertIsNone(snapshot.last_error)
        finally:
            bridge.close()

    def test_missing_or_empty_command_id_in_ack_does_not_confirm(self):
        transport = FakeTransport()
        bridge = Esp32Bridge(transport)
        try:
            bridge.send_decision("ins-1", "PASS")
            # ACK without command_id
            transport.reads.append(b'{"schema_version":1,"type":"command.ack","status":"ACCEPTED","ok":true}\n')
            time.sleep(0.05)
            snap = bridge.snapshot()
            self.assertEqual(snap.last_command_state, "sent_unconfirmed")
            self.assertEqual(snap.indicator, "off")
            self.assertIn("missing command_id", snap.last_error or "")
        finally:
            bridge.close()

    def test_mismatched_command_id_ignored_and_does_not_confirm(self):
        transport = FakeTransport()
        bridge = Esp32Bridge(transport)
        try:
            bridge.send_decision("ins-1", "PASS")
            # ACK with completely different command_id
            bad_ack = json.dumps({
                "schema_version": 1,
                "type": "command.ack",
                "command_id": "different-uuid",
                "status": "ACCEPTED",
                "ok": True,
            }) + "\n"
            transport.reads.append(bad_ack.encode())
            time.sleep(0.05)
            snap = bridge.snapshot()
            self.assertEqual(snap.last_command_state, "sent_unconfirmed")
            self.assertEqual(snap.indicator, "off")
        finally:
            bridge.close()

    def test_older_acknowledgment_cannot_confirm_newer_command(self):
        transport = FakeTransport()
        bridge = Esp32Bridge(transport)
        try:
            bridge.send_decision("ins-1", "PASS")
            cmd_1 = json.loads(transport.writes[-1])["command_id"]

            # Send a second decision before first was ACKed
            bridge.send_decision("ins-2", "FAIL")
            cmd_2 = json.loads(transport.writes[-1])["command_id"]
            self.assertNotEqual(cmd_1, cmd_2)
            self.assertEqual(bridge.snapshot().last_command_id, cmd_2)
            self.assertEqual(bridge.snapshot().last_command_state, "sent_unconfirmed")
            self.assertEqual(bridge.snapshot().indicator, "off")

            # Belated ACK for command 1 arrives:
            belated_ack = json.dumps({
                "schema_version": 1,
                "type": "command.ack",
                "command_id": cmd_1,
                "status": "ACCEPTED",
                "ok": True,
            }) + "\n"
            transport.reads.append(belated_ack.encode())
            time.sleep(0.05)

            # Must NOT confirm command 2 or set indicator
            snap = bridge.snapshot()
            self.assertEqual(snap.last_command_id, cmd_2)
            self.assertEqual(snap.last_command_state, "sent_unconfirmed")
            self.assertEqual(snap.indicator, "off")

            # Now send valid ACK for command 2
            valid_ack = json.dumps({
                "schema_version": 1,
                "type": "command.ack",
                "command_id": cmd_2,
                "status": "ACCEPTED",
                "ok": True,
            }) + "\n"
            transport.reads.append(valid_ack.encode())
            deadline = time.time() + 1
            while time.time() < deadline and bridge.snapshot().last_command_state != "acknowledged":
                time.sleep(0.01)

            final_snap = bridge.snapshot()
            self.assertEqual(final_snap.last_command_state, "acknowledged")
            self.assertEqual(final_snap.indicator, "fail")
        finally:
            bridge.close()

    def test_rejected_command_and_error_message_fail_safely(self):
        transport = FakeTransport()
        bridge = Esp32Bridge(transport)
        try:
            bridge.send_decision("ins-1", "FAIL")
            cmd_id = json.loads(transport.writes[-1])["command_id"]

            reject_ack = json.dumps({
                "schema_version": 1,
                "type": "command.ack",
                "command_id": cmd_id,
                "status": "REJECTED",
                "ok": False,
                "error_code": "ERR_FIELD_INVALID",
            }) + "\n"
            transport.reads.append(reject_ack.encode())

            deadline = time.time() + 1
            while time.time() < deadline and bridge.snapshot().last_command_state != "rejected":
                time.sleep(0.01)

            snap = bridge.snapshot()
            self.assertEqual(snap.last_command_state, "rejected")
            self.assertEqual(snap.indicator, "off")
            self.assertEqual(snap.last_error, "ERR_FIELD_INVALID")
        finally:
            bridge.close()

    def test_write_failure_fails_safely_and_disconnects(self):
        transport = FakeTransport()
        bridge = Esp32Bridge(transport)
        try:
            with self.assertRaises(ValueError):
                bridge.send_decision("ins-1", "INVALID_VERDICT")
            transport.write = lambda _data: (_ for _ in ()).throw(OSError("UART write error"))
            bridge.send_decision("ins-1", "UNVERIFIED")
            snap = bridge.snapshot()
            self.assertEqual(snap.state, "disconnected")
            self.assertEqual(snap.last_command_state, "write_failed")
            self.assertEqual(snap.indicator, "off")
            self.assertIn("UART write error", snap.last_error or "")
        finally:
            bridge.close()

    def test_stale_sensor_and_heartbeat_timeout(self):
        transport = FakeTransport()
        bridge = Esp32Bridge(transport, stale_after_s=0.1)
        try:
            # Receive sensor state
            transport.reads.append(b'{"schema_version":1,"type":"sensor.state","sensor_active":true}\n')
            deadline = time.time() + 1
            while time.time() < deadline and bridge.snapshot().sensor_active is None:
                time.sleep(0.01)
            self.assertEqual(bridge.snapshot().state, "connected")

            # Wait beyond stale timeout
            time.sleep(0.15)
            stale_snap = bridge.snapshot()
            self.assertEqual(stale_snap.state, "stale")
            self.assertEqual(stale_snap.indicator, "off")
            self.assertEqual(stale_snap.last_error, "sensor data stale")
        finally:
            bridge.close()

    def test_reconnect_handling(self):
        transport_1 = FakeTransport()
        bridge = Esp32Bridge(transport_1)
        try:
            bridge.send_decision("ins-1", "PASS")
            # Simulate disconnect via transport read error
            transport_1.readline = lambda: (_ for _ in ()).throw(OSError("device removed"))
            time.sleep(0.05)
            self.assertEqual(bridge.snapshot().state, "disconnected")

            # Reconnect with fresh transport
            transport_2 = FakeTransport()
            bridge.reconnect(transport_2)
            self.assertEqual(bridge.snapshot().state, "connected")
            self.assertTrue(transport_1.closed)

            # Send hello on new transport
            transport_2.reads.append(b'{"schema_version":1,"type":"hello","firmware_version":"1.0.0"}\n')
            deadline = time.time() + 1
            while time.time() < deadline and bridge.snapshot().firmware_version is None:
                time.sleep(0.01)
            self.assertEqual(bridge.snapshot().firmware_version, "1.0.0")
        finally:
            bridge.close()

    def test_disabled_hardware_returns_safe_defaults(self):
        disabled = DisabledHardware()
        snap = disabled.snapshot()
        self.assertFalse(snap.enabled)
        self.assertEqual(snap.state, "disabled")
        self.assertEqual(snap.indicator, "off")
        self.assertIsNone(snap.last_command_id)
        # Verify safe no-ops
        disabled.send_decision("ins-1", "PASS")
        disabled.close()


if __name__ == "__main__":
    unittest.main()

