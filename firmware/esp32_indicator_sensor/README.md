# ESP32 indicator + IR sensor firmware

Arduino-compatible, PlatformIO-buildable firmware for an **ESP32 DevKit V1**.
This slice intentionally implements only the presence sensor, two decision LEDs,
and a bounded USB-serial protocol. It does **not** implement motor, servo, PWM,
driver-enable, or arbitrary GPIO control.

## Pin assignments

Assignments match the physically tested breadboard wiring:

| Signal | GPIO | DevKit Pin | Behavior |
|---|---:|:---:|---|
| Red FAIL LED | GPIO 5 | D5 | Active HIGH, series resistor required |
| Green PASS LED | GPIO 4 | D4 | Active HIGH, series resistor required |
| IR presence digital output | GPIO 23 | D23 | Input with internal pull-up (`INPUT_PULLUP`); active LOW |
| IR sensor VCC | 3.3 V | 3V3 | Power from ESP32 3.3 V rail only |
| IR sensor GND | GND | GND | Common ground with ESP32 |

`IR_SENSOR_ACTIVE_LEVEL`, `SENSOR_DEBOUNCE_MS`, `HEARTBEAT_TIMEOUT_MS`, LED
polarity, and all pins are compile-time constants in `src/main.cpp`. GPIO 23 is
configured with internal pull-up (`pinMode(IR_SENSOR_GPIO, INPUT_PULLUP)`),
maintaining a stable HIGH idle state when no object is reflecting IR.

## Safety and electrical boundaries

- GPIOs and power rails are **3.3 V only**. Never apply a 5 V sensor output.
- Drive each LED through a correctly sized series resistor (e.g., 220 Ω – 330 Ω).
- Do not connect a motor, servo, relay coil, or other high-current load to an
  ESP32 GPIO or breadboard power rail. Motor control is deliberately absent here.
- Keep the manual motor controller (9 V battery + PWM speed controller)
  electrically isolated from the ESP32 logic and power.
- Keep this supervised tabletop prototype away from mains, PLC safety circuits,
  production machinery, and personnel-protection systems.

## Fail-safe timeout and disconnect behavior

- On boot, both LEDs are forced OFF during the `STARTUP_SAFE_MS` window before serial starts.
- If no valid heartbeat or fresh disposition is received within 5 seconds (`HEARTBEAT_TIMEOUT_MS`),
  the connection is marked `STALE`, `outcome` resets to `UNVERIFIED`, and both LEDs turn OFF and stay OFF.
- When serial disconnect occurs, the host bridge marks state as `disconnected`,
  records `write_failed` for outstanding commands, and clears indicator state to `off`.
- `PASS` turns green on; `FAIL` turns red on; `UNVERIFIED` turns both off.
  Indicators are status hints, not proof of physical handling or safety.

## Newline-delimited protocol

Serial is 115200 8N1. Each message is one JSON object terminated by `\n`, with a
maximum line length of 1024 bytes. Input is bounded and rejected without changing
the LEDs when malformed, unsupported, missing required fields, or oversized.

### Host commands

```json
{"schema_version":1,"type":"heartbeat"}
{"schema_version":1,"type":"inspection.disposition","command_id":"cmd_01a2b3c4","inspection_id":"insp-0001","decision":"PASS"}
{"schema_version":1,"type":"inspection.disposition","command_id":"cmd_01a2b3c5","inspection_id":"insp-0002","decision":"FAIL"}
{"schema_version":1,"type":"inspection.disposition","command_id":"cmd_01a2b3c6","inspection_id":"insp-0003","decision":"UNVERIFIED"}
{"schema_version":1,"type":"controller.status.request"}
{"schema_version":1,"type":"sensor.status.request"}
```

### Firmware responses

- Startup emits `hello`:
  `{"schema_version":1,"type":"hello","firmware_version":"1.0.0","state":"READY",...}`
- Sensor state change emits `sensor.state`:
  `{"schema_version":1,"type":"sensor.state","sensor":"ir_presence","sensor_active":true,"active":true,"raw_active":true,"sequence":1}`
- Periodic sensor snapshot emits `sensor.status`:
  `{"schema_version":1,"type":"sensor.status","firmware_version":"1.0.0","state":"READY",...}`
- Valid disposition emits `command.ack` echoing `command_id` and indicating acceptance:
  `{"schema_version":1,"type":"command.ack","command_id":"cmd_01a2b3c4","inspection_id":"insp-0001","status":"ACCEPTED","ok":true,"outcome":"PASS","controller_state":"INDICATOR_ONLY"}`
- Rejected disposition emits `command.ack` with `ok: false`:
  `{"schema_version":1,"type":"command.ack","command_id":"cmd_...","inspection_id":"...","status":"REJECTED","ok":false,"error_code":"ERR_FIELD_INVALID"}`
- Protocol errors emit `error`:
  `{"schema_version":1,"type":"error","error_code":"ERR_BAD_JSON"}`

### Delivery and confirmation semantics

1. Sending a command puts the bridge into `sent_unconfirmed`.
2. The host bridge does **not** optimistically set the indicator state on send.
3. The bridge's confirmed indicator state updates only after receiving a matching `command.ack` with `ok: true`.
4. Acknowledgments for older or mismatched `command_id`s are ignored and never confirm a newer command.

## Build and upload

PlatformIO build configuration is in `platformio.ini` (`board = esp32doit-devkit-v1`, `framework = arduino`).

*Note:* When `pio` / `platformio` CLI is not installed locally, compilation remains **unverified** until compiled.

To compile and upload when PlatformIO is available:

```bash
pio run -d firmware/esp32_indicator_sensor
pio run -d firmware/esp32_indicator_sensor --target upload
pio device monitor -d firmware/esp32_indicator_sensor --baud 115200
```

Alternatively, open `firmware/esp32_indicator_sensor/src/main.cpp` in the Arduino IDE, select **ESP32 Dev Module** or **DOIT ESP32 DEVKIT V1**, and click **Upload**.

