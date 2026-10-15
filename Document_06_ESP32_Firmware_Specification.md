# Document 06 — ESP32 Firmware Specification
**Project:** Agentic AI Smart Manufacturing Quality Inspection & Automation Platform  
**Document version:** 1.0  
**Date:** 15 October 2026  
**Status:** Firmware contract and safety specification — exact pins/driver remain provisional  
**Owner:** Embedded Systems Engineering  
**Related documents:** Documents 01–05; Production-Grade PRD v3.0

---

## 1. Purpose and boundary

Define the firmware responsibilities and communication contract for the ESP32-class controller used in the supervised tabletop prototype. The ESP32 reads simple sensors, controls status indicators, and issues bounded motor-driver/servo outputs. The laptop remains the decision authority for image inference and `PASS` / `FAIL` / `UNVERIFIED`.

**The ESP32 must not:**
- Run or reinterpret the AI model or decide whether an item is defective.
- Accept arbitrary shell commands, code, pin numbers, PWM values or unbounded movement commands from the laptop.
- Allow an LLM/agent to directly command GPIO, motor speed, servo angle or safety behavior.
- Treat a missing response, malformed packet, unknown command or reboot as `PASS`.
- Claim an item was physically rejected merely because a servo command was sent.

This is a low-voltage, supervised tabletop prototype—not a certified industrial safety controller. Do not connect it to a real production line, PLC safety circuit, emergency-stop loop, mains-powered machinery, or personnel-protection system.

## 2. Responsibilities

| Component | Responsibility | Must not do |
|---|---|---|
| Laptop application | Capture image, run model, apply approved decision policy, assign inspection ID, request bounded action, persist result | Assume command success without acknowledgement/state confirmation |
| ESP32 firmware | Sensor readout, status LEDs, validated command handling, motor-driver interface, servo sequence, heartbeat and acknowledgements | Decide quality from scores or expose unrestricted GPIO |
| Motor driver | Switch motor power within its rated voltage/current/thermal limits | Be powered through ESP32 GPIO |
| External motor/servo supplies | Deliver current required by motor/servo | Feed high-current loads through the ESP32 regulator |
| Physical stop/power disconnect | Remove or inhibit hazardous motion in this supervised prototype | Be replaced by a software-only command |

The physical stop and wiring arrangement must be reviewed before the first powered test. Firmware is a second layer of control, not the only means to stop moving hardware.

## 3. State model

Use an explicit state machine. Do not implement the workflow as a loose collection of flags.

| State | Meaning | Permitted outputs |
|---|---|---|
| `BOOT_SAFE` | Reset/boot sequence; output defaults being established | Motor disabled; servo not commanded to reject; amber/status indication if safe |
| `IDLE` | No active inspection; waiting for laptop command or permitted sensor event | Motor stopped by default; green may indicate controller ready, not product PASS |
| `PART_PRESENT` | Sensor indicates an object at the inspection point | Motor stop request; notify laptop; no verdict implied |
| `INSPECTION_HELD` | Laptop owns active inspection and belt is held | Motor disabled; await terminal command |
| `PASS_COMPLETE` | Laptop authorized PASS disposition | Green indicator; no reject movement |
| `FAIL_REJECTING` | Valid FAIL command accepted and reject sequence is active | Red indicator; one bounded servo movement |
| `FAIL_COMPLETE` | Reject sequence completed and returned to safe position | Red/status; motor remains stopped until explicit resume policy permits |
| `UNVERIFIED_HOLD` | Input/model/communication outcome is unknown or unresolved | Amber indicator; no automatic accept/reject; hold |
| `FAULT_LATCHED` | Critical firmware, sensor, driver, timeout or inconsistent state fault | Motor disabled; fault indicator; require explicit recovery |
| `ESTOP_OR_POWER_OFF` | Physical stop engaged or power removed | Motion inhibited by physical arrangement; software state is informational only |

The final motor-resume behavior must be set in the machine-control policy. The initial prototype should keep the belt stopped through capture, inference, reject, and unresolved `UNVERIFIED`; resumption requires a defined, explicit command after the part is handled.

### 3.1 State transition rules

- Boot and brownout enter `BOOT_SAFE`; motor enable defaults inactive.
- A sensor edge is debounced and converted into at most one part-present event until the sensor clears.
- `INSPECTION_HELD` is entered only with a valid active inspection ID.
- A `PASS` command is accepted only for the active ID and only when no critical fault exists.
- A `FAIL` command is accepted only once per inspection ID. Repeated command delivery returns the previous action status and must not repeat the servo stroke.
- `UNVERIFIED` enters `UNVERIFIED_HOLD`; it does not invoke the reject servo by default.
- Any malformed command, invalid state transition, timeout or inconsistent hardware state returns an error and never creates a PASS.
- Reset during a reject stroke must not automatically replay the reject. After reboot, report unknown/needs-review for the interrupted inspection and remain safe.
- Fault clear requires an explicit recovery operation and any required physical inspection; do not clear a latched fault just because the laptop reconnects.

## 4. Hardware abstraction and provisional pin plan

The exact ESP32 board, sensor module, motor driver and servo have not yet been selected. Pin numbers below are **illustrative placeholders** and must be checked against the exact board's pinout, boot-strapping pins, input-only pins, peripheral support and voltage levels.

| Signal | Example ESP32 GPIO | Direction | Notes |
|---|---:|---|---|
| Part-presence sensor digital output | GPIO 27 | Input | Confirm sensor output voltage and active polarity |
| Green LED | GPIO 18 | Output via resistor/driver as appropriate | Controller/product status must be labelled clearly |
| Red LED | GPIO 19 | Output via resistor/driver as appropriate | FAIL / fault indication defined by UI/state |
| Amber LED | GPIO 21 | Output via resistor/driver as appropriate | UNVERIFIED / attention |
| Motor-driver enable | GPIO 25 | Output | Hardware pull-down/disable default recommended where supported |
| Motor-driver direction (if required) | GPIO 26 | Output | Only if the selected driver needs it |
| Servo signal | GPIO 13 | PWM-capable output | Servo gets a suitable external supply; shared signal reference |
| Optional driver fault input | GPIO 32 | Input | Only if selected driver exposes a compatible fault signal |
| Optional physical stop status sense | GPIO 33 | Input | Informational only; physical power/motion inhibit must not depend on firmware |

Use the ESP32 board's documented logic level. Do not apply 5 V to a non-5-V-tolerant GPIO. Use a level shifter or compatible sensor output if needed. Choose safe pins based on the exact board; the example above is not a final wiring diagram.

### 4.1 Electrical rules

- Never power a DC motor or servo from an ESP32 GPIO pin.
- Use a motor driver rated for the motor's supply voltage, normal running current, startup/stall current, duty cycle and thermal environment.
- Size the motor supply and wiring for startup/stall conditions, not just the no-load current printed in an informal listing.
- Power the servo from a suitable external supply with adequate transient current. Join supply ground and ESP32 signal ground where required by the selected design; avoid routing servo/motor current through the board's ground traces.
- Fit the driver-required flyback/clamp protection. Many modules include protection, but verify the exact board and datasheet rather than assuming.
- Use a fuse/current limit appropriate to the supply and wiring. Keep exposed conductors insulated and strain-relieved.
- Keep motor wiring away from sensor/signal wiring where practical. Add appropriate decoupling and transient suppression per component datasheets.
- Physical stop/power disconnect should interrupt motor energy independently of software. Design the circuit around the selected low-voltage supply and have the wiring checked before power-on.
- Do not use mains voltage on the tabletop conveyor.

## 5. Communication transport

The first implementation may use USB serial between laptop and ESP32 because it is easy to observe and keep local. A local network transport may be considered later, but both transports must implement the same command schema and state rules.

Serial defaults are provisional:
- Baud rate: `115200`
- 8 data bits, no parity, 1 stop bit (8N1)
- UTF-8 JSON, one complete JSON object per line, terminated by `\n`
- Maximum input line length: 1024 bytes
- Maximum JSON nesting and field counts should be bounded by the parser/configuration
- Invalid or oversized lines are rejected and logged; do not parse partial lines as commands

Do not treat serial port opening as authentication. Limit physical USB access during testing and avoid accepting control messages from untrusted hosts.

## 6. Protocol contract

Every command has a schema version and unique command ID. Every inspection-related command includes a stable inspection ID. IDs must be validated for length/character set and stored in a bounded recent-result ledger so retries are idempotent.

### 6.1 Example laptop command

```json
{
  "schema_version": 1,
  "type": "inspection.disposition",
  "command_id": "cmd-000042",
  "inspection_id": "insp-20261015-000042",
  "decision": "FAIL",
  "policy_version": "policy_v1",
  "requested_at_utc": "2026-10-15T12:00:00Z"
}
```

This is a schema example, not a real command or authorization. The firmware accepts only enumerated decisions: `PASS`, `FAIL`, `UNVERIFIED`. It ignores any score, prompt, shell string, free-form action, requested pin, raw PWM or arbitrary angle in a laptop payload.

### 6.2 Example acknowledgement

```json
{
  "schema_version": 1,
  "type": "command.ack",
  "command_id": "cmd-000042",
  "inspection_id": "insp-20261015-000042",
  "status": "ACCEPTED",
  "controller_state": "FAIL_REJECTING",
  "action_id": "act-insp-20261015-000042",
  "error_code": null
}
```

Acceptance means the firmware validated and accepted the command; it does **not** prove the physical action completed. Emit a separate completion event after the servo sequence and required state checks.

### 6.3 Required message types

| Message | Direction | Purpose |
|---|---|---|
| `hello` / `controller.status` | ESP32 → laptop | Firmware version, boot ID, capabilities, current state, fault flags |
| `heartbeat` | Laptop → ESP32 | Link health; no quality decision |
| `sensor.part_present` | ESP32 → laptop | Debounced presence event with sensor sequence |
| `inspection.hold` | Laptop → ESP32 | Hold the conveyor for a named inspection |
| `inspection.disposition` | Laptop → ESP32 | Apply PASS/FAIL/UNVERIFIED for the active inspection |
| `machine.resume` | Laptop → ESP32 | Explicitly resume only if current state and policy permit |
| `command.ack` | ESP32 → laptop | Validation/acceptance result |
| `action.completed` | ESP32 → laptop | Servo sequence or other bounded action completed |
| `fault.raised` / `fault.cleared` | ESP32 → laptop | Fault reporting and recovery audit |
| `inspection.status` | ESP32 → laptop | State/status query for an inspection ID |

The laptop must persist its own inspection decision and correlation IDs before/while issuing commands. The controller's recent-result ledger is a duplicate-protection aid, not the system's sole audit database.

## 7. Validation and error codes

The firmware validates:
- Schema version and message type.
- Required fields, field types and maximum lengths.
- Enum values and legal state transition.
- Active inspection ID and duplicate command ID.
- Command expiry/staleness if the protocol uses a timestamp/expiry field.
- Controller readiness, fault state and action interlocks.
- Rate limits and payload length.

Suggested error codes:

| Code | Meaning |
|---|---|
| `ERR_BAD_JSON` | JSON invalid or incomplete |
| `ERR_SCHEMA_VERSION` | Unsupported schema |
| `ERR_UNKNOWN_COMMAND` | Command type not supported |
| `ERR_FIELD_INVALID` | Missing/invalid field or value |
| `ERR_STATE_CONFLICT` | Command not allowed in current state |
| `ERR_INSPECTION_ID_MISMATCH` | ID does not match active inspection |
| `ERR_DUPLICATE` | Command already processed; prior status returned |
| `ERR_STALE_COMMAND` | Command is outside allowed age/window |
| `ERR_FAULT_LATCHED` | Critical fault blocks action |
| `ERR_ACTION_BUSY` | Another bounded action is in progress |
| `ERR_SENSOR_UNAVAILABLE` | Required sensor cannot be trusted |
| `ERR_ACTUATOR_TIMEOUT` | Action did not complete within its bound |
| `ERR_NOT_READY` | Boot or self-check not complete |

Error responses should contain a stable code and safe current state, not internal stack traces or arbitrary data. Log enough context to diagnose without dumping secrets or unbounded input.

## 8. Command idempotency and duplicate protection

- Maintain a bounded ledger keyed by `command_id` and `inspection_id`.
- If the same command is retried, return the recorded status; do not repeat motor/servo motion.
- If a new command ID attempts to FAIL the same inspection ID after the action is already complete, return the prior action status and do not actuate again.
- Reject contradictory decisions for one inspection ID unless an explicit reviewed correction workflow exists; do not turn a previously completed PASS into a FAIL action under the same ID.
- On controller reboot, persistent idempotency storage may not be available in the first prototype. Therefore, boot must report a new `boot_id`, and the laptop must reconcile interrupted inspections. Never automatically replay an uncertain action after reboot.
- Test the behavior for a lost acknowledgement, duplicate packet, delayed packet, reconnect, and reboot.

## 9. Motor and servo command boundaries

The laptop protocol does not supply arbitrary servo angles or motor PWM values. Firmware owns a small set of named, compiled action profiles.

Example named profile identifiers:
- `MOTOR_STOP`
- `MOTOR_RUN_INSPECTION_SPEED` (only after a separate motor-control policy and driver are qualified)
- `REJECT_STROKE_V1`
- `SERVO_SAFE_POSITION`
- `INDICATOR_PASS`
- `INDICATOR_FAIL`
- `INDICATOR_UNVERIFIED`
- `INDICATOR_FAULT`

The initial implementation should prioritize motor disabled/stopped during capture and inference. Exact motor speed, servo safe/reject positions, stroke duration and mechanical clearances must be calibrated on the actual hardware. Limit motion duration, clamp any internally calculated PWM to tested ranges, and abort/disable the driver on timeout or inconsistent state.

The servo mechanism should move only a lightweight test object with a guarded travel path. Keep fingers clear, test without an object first, and verify the arm cannot jam against the belt/frame. A commanded servo angle is not proof that the object was successfully diverted; a reject confirmation sensor can be added later if required.

## 10. Watchdogs, timeouts and fault handling

Set concrete timeout values only after measuring the selected hardware. Every timeout must have an explicit outcome.

| Condition | Required behavior |
|---|---|
| Laptop heartbeat lost | Stop/disable motor; preserve safe state; raise link fault after configured timeout |
| Invalid command or oversized payload | Reject; do not alter actuator state |
| Sensor stuck active | Raise sensor fault after a measured/defined duration; no endless repeated part events |
| Sensor disconnected/unreliable | Mark required sensor unavailable; block automatic cycle |
| Servo action exceeds bound | Disable motor; report `ERR_ACTUATOR_TIMEOUT`; latch fault if appropriate |
| Motor driver reports fault | Disable enable output; latch fault; require diagnosis |
| ESP32 watchdog/reset | Hardware defaults should leave motor disabled; report new boot ID on reconnect |
| Laptop/model timeout | Laptop sends `UNVERIFIED`/hold under its policy; ESP32 does not infer a disposition |
| Power interruption during reject | No automatic action replay after restart; inspection is unresolved until reconciled |
| Serial buffer overflow | Drop invalid input safely; increment diagnostic counter; no partial command execution |

Use the ESP32 watchdog and non-blocking task design appropriate to the chosen framework. Avoid long `delay()` loops that prevent sensor handling, watchdog service, communication processing, or fault detection.

## 11. Indicator semantics

| LED | Meaning | Notes |
|---|---|---|
| Green | Controller ready or approved PASS, depending on a clearly defined display mode | Do not conflate “controller ready” with “item passed”; consider separate ready/status indicator |
| Red | FAIL disposition or critical fault, distinguished by blink pattern or dashboard text | Must be unambiguous to the operator |
| Amber | UNVERIFIED, manual review or attention required | No automatic acceptance/rejection |
| All indicators off | Power absent or indicator circuit failure | Do not assume this means safe without checking motion/power |

Define a small set of documented patterns (steady, slow blink, fast fault blink) and avoid ambiguous multi-meaning patterns. The operator dashboard and firmware should use the same state names.

## 12. Firmware architecture

Recommended modules:
- `main` / startup: initialize safe outputs and report firmware/boot identity.
- `state_machine`: validates state transitions and owns the authoritative controller state.
- `protocol`: bounded line reader, JSON validation, command/response serialization.
- `sensor_manager`: debounce and report sensor events.
- `motor_driver`: driver-specific enable/direction/speed abstraction; defaults disabled.
- `servo_controller`: named bounded action profiles, no remote arbitrary angle.
- `indicator_manager`: state/fault display.
- `watchdog_health`: heartbeat, task health, fault counters and timeout enforcement.
- `idempotency_ledger`: recent commands/inspection outcomes.
- `diagnostics`: version, uptime, boot ID, fault state and bounded logs.

Do not mix parsing, state transitions and GPIO writes in one callback. Validate the full command, check state and interlocks, reserve the action/inspection ID, then perform the bounded action in a non-blocking state machine and emit completion.

## 13. Suggested repository layout

Adapt to the actual repository and framework rather than creating a second firmware project blindly.

```text
firmware/
  esp32_controller/
    README.md
    platformio.ini              # if PlatformIO is selected
    src/
      main.cpp
      state_machine.cpp
      protocol.cpp
      sensor_manager.cpp
      motor_driver.cpp
      servo_controller.cpp
      indicator_manager.cpp
      watchdog_health.cpp
    include/
      config.h
      protocol_types.h
    test/
      test_protocol/
      test_state_machine/
    docs/
      pin_map.md
      bench_test_record.md
```

If the project uses Arduino IDE or ESP-IDF rather than PlatformIO, preserve the same module boundaries and document the chosen build environment.

## 14. Verification plan

### 14.1 Unit tests (no powered motor/servo)
- Valid/invalid JSON and maximum line length.
- Unknown schema, message type, field and decision.
- All legal/illegal state transitions.
- Missing or mismatched inspection ID.
- Duplicate command ID and repeated FAIL for one inspection.
- Stale/expired command.
- Error and timeout state transitions.
- Indicator mapping for each controller state.
- Reboot/reconciliation behavior and bounded ledger overflow.

### 14.2 Bench tests (actuators disconnected first)
- Boot/reset leaves motor enable inactive.
- Sensor input debounce produces one event per presence cycle.
- LED polarity and meaning match the specification.
- Serial disconnect/reconnect is detected.
- Watchdog and heartbeat timeout create a visible fault without motion.
- Malformed input never toggles a motor/servo pin.
- Brownout/reset tests performed with safe, current-limited low-voltage equipment.

### 14.3 Supervised actuator tests
Only after driver/supply/pinout are confirmed and the physical stop/power disconnect is installed:
1. Test motor driver with belt unloaded and the reject servo disconnected.
2. Verify motor stop response and timeout behavior.
3. Test servo with no object and limited mechanical travel.
4. Run one lightweight test object in a guarded area.
5. Exercise PASS (no reject), FAIL (one reject stroke), and UNVERIFIED (hold/no automatic reject).
6. Send duplicate and delayed FAIL commands; verify no second stroke.
7. Interrupt communication and reset power; verify no automatic replay.
8. Record firmware hash, board/driver part IDs, supply voltage/current limit, test operator and outcome.

Do not run the reject arm while hands are near the linkage. Stop testing immediately if the belt, frame, servo or wiring overheats, jams, vibrates unexpectedly or behaves inconsistently.

## 15. Firmware acceptance criteria

- `FW-01`: Safe outputs are established before communication starts.
- `FW-02`: Invalid/unknown commands never cause actuator motion.
- `FW-03`: Only enumerated decisions and named action profiles are accepted.
- `FW-04`: PASS changes indicators only and never triggers reject.
- `FW-05`: FAIL triggers at most one bounded reject sequence per inspection ID.
- `FW-06`: UNVERIFIED holds and indicates amber; no automatic PASS or reject.
- `FW-07`: Duplicate command delivery is idempotent.
- `FW-08`: Lost heartbeat, sensor fault, driver fault and action timeout have defined safe outcomes.
- `FW-09`: Physical stop/power disconnect remains independent of firmware.
- `FW-10`: Laptop can query controller version, boot ID, state and fault information.
- `FW-11`: Reboot does not replay an uncertain reject action.
- `FW-12`: All tests are recorded against the actual firmware build and hardware identifiers.

## 16. Open decisions

| ID | Decision | Current status |
|---|---|---|
| D06-01 | Exact ESP32 board and revision | Open |
| D06-02 | Framework: ESP-IDF, Arduino or PlatformIO workflow | Open |
| D06-03 | Presence sensor type/output polarity | Open |
| D06-04 | Motor and motor driver ratings | Open; must be selected from measured motor stall current and supply |
| D06-05 | Servo model, supply and safe/reject geometry | Open |
| D06-06 | Serial versus local network transport | USB serial recommended for first implementation |
| D06-07 | Exact pin map | Provisional until board confirmed |
| D06-08 | Timeout values and motor resume policy | Set after measurement and hazard review |
| D06-09 | Whether a reject-confirmation sensor is required | Open |
| D06-10 | Physical stop/power disconnect circuit | Must be reviewed before powered actuator tests |

## 17. Immediate implementation order

1. Identify the actual ESP32 board and record its pinout/logic levels.
2. Select the framework and create a buildable skeleton.
3. Implement safe boot, controller status and bounded serial protocol with all actuators disconnected.
4. Implement the state machine and unit tests.
5. Add LEDs and presence sensor; verify events and debounce.
6. Select motor driver/supply only after confirming the motor's electrical ratings.
7. Add motor/servo abstractions with outputs disabled by default.
8. Test idempotency, lost acknowledgement, heartbeat timeout, reboot and malformed inputs.
9. Install and review the physical stop/power disconnect before actuator tests.
10. Integrate with the laptop only after the protocol tests pass; keep AI inference and physical control separated.

## 18. References

1. Espressif ESP32 documentation: https://docs.espressif.com/projects/esp-idf/en/stable/esp32/
2. Espressif ESP-IDF FreeRTOS / task watchdog documentation: https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-reference/system/wdts.html
3. Espressif GPIO documentation: https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-reference/peripherals/gpio.html

Consult the datasheet and technical reference for the exact ESP32 board, motor driver, sensor and servo before finalizing pin mapping, current limits or electrical connections.
