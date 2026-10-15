# Document 02 — Hardware Design & Bill of Materials

**Project:** Agentic AI Smart Manufacturing Quality Inspection & Automation Platform  
**Document ID:** HW-02  
**Status:** Prototype design baseline — parts not yet frozen  
**Version:** 1.0  
**Prepared:** 15 October 2026

## 1. Purpose and design boundary

This document defines a safe, low-voltage tabletop prototype that moves one lightweight test item into a camera inspection position, pauses the conveyor, waits for the laptop inspection service, and then either releases the item or actuates a small reject flap. The laptop remains the inspection decision authority. The ESP32 handles sensors, motor-driver signals, indicators, and the servo only after receiving an explicit, bounded command.

The intended prototype is a learning/demo rig, not a certified industrial machine. It must not be connected to a factory PLC, production conveyor, machine guard interlock, or safety circuit. Keep mains voltage inside a certified, enclosed AC/DC adapter; do not build exposed mains wiring.

**Design assumptions:**
- Existing laptop/PC provides model inference and the operator dashboard.
- A borrowed phone is the camera; use USB webcam mode or a local network stream, depending on the phone and app.
- ESP32 is powered by USB or a regulated supply; motor and servo have separate power paths.
- Lightweight, hand-placed test items; exact size, mass, surface, and defect class are not yet selected.
- The belt stops during capture/inference and remains stopped for UNVERIFIED/manual review.
- The reject arm diverts an item into a tray; it must not strike a person or trap fingers.

## 2. Proposed tabletop layout

Start with a frame approximately **450 mm long × 180 mm wide**, with a belt width around **100–120 mm** and a belt travel length around **300–350 mm**. These are provisional workshop dimensions, not final design values. Revise them once the item category and camera field of view are selected.

Place components in this order along belt travel:

1. **Infeed area:** operator places one item at a time.
2. **Presence sensor:** detects the leading edge of an item before the inspection station.
3. **Inspection zone:** item rests inside the phone camera's fixed field of view, with diffuse, consistent lighting.
4. **Reject point:** downstream flap/arm directs FAIL items into a side tray while the belt is stopped.
5. **Pass outfeed:** PASS items continue to the normal end of the belt after the decision.

The camera should be mounted on a rigid overhead bracket, with the lens approximately perpendicular to the inspected surface. Keep the camera, object, and lighting geometry fixed between training-data capture and live inspection. Prevent direct glare, shadows, and auto-exposure changes where possible. Use a matte background with a contrasting colour only after reviewing the dataset/model requirements.

## 3. Bill of materials

Prices below are **planning estimates in Indian rupees**, not quotations. Online prices, stock, tax, and shipping can change. Reference prices were visible on Indian electronics retail pages on 15 October 2026; check the exact part, variant, stock, and delivery charge before ordering.

| # | Item | Qty. | Budget estimate (INR) | Selection notes |
|---|---|---:|---:|---|
| 1 | ESP32 DevKit development board | 1 | 400–550 | Standard ESP32 with USB programming and 3.3 V GPIO. Example catalogue listing: ₹449. |
| 2 | Presence sensor | 1 | 45–350 | Prefer a break-beam / through-beam sensor for repeatable edge detection; a reflective IR module can be used for early tests if its range and surface sensitivity are acceptable. |
| 3 | 12 V DC geared motor, low speed | 1 | 200–700 | A 10–30 RPM example is a starting point only. Confirm shaft, mounting, output torque, rated current and stall current before choosing the driver. |
| 4 | DC motor driver | 1 | 200–800 | Choose only after motor stall current and supply voltage are known. Driver continuous current and thermal limits must exceed the expected load. The large BTS7960 module is not automatically the best choice for a small motor. |
| 5 | 12 V DC power adapter, approx. 5 A | 1 | 430–600 | Use a reputable, enclosed adapter with overload/short-circuit protection. Actual current rating depends on motor start/stall current and other 12 V loads. |
| 6 | Servo, metal-geared, e.g. MG996R-class | 1 | 270–500 | For a small reject flap. Choose linkage geometry and servo torque after estimating flap force; avoid holding the servo at stall. |
| 7 | Dedicated regulated servo supply | 1 | 200–450 | Regulated 5–6 V supply/buck rated for the servo's peak current, often several amps for a large servo. Do not power servo from ESP32 5 V/GPIO. |
| 8 | Belt material | 1 | 250–600 | Rubber sheet, thin PU belt or suitable flexible sheet; provide enough grip without excessive drag. A joined belt loop must be smooth. |
| 9 | Rollers, shafts, bearings and brackets | set | 400–900 | Two rollers plus shafts/bearings. Reuse suitable parts if available; ensure both rollers are parallel and guarded. |
| 10 | Frame/base material | set | 350–800 | Plywood/MDF/acrylic or aluminium extrusion. Ensure rigidity and accessible mounting points. |
| 11 | Motor coupling, mount and fasteners | set | 200–450 | Coupling must suit the exact motor shaft and roller shaft. Avoid misalignment that loads the gearbox. |
| 12 | Reject flap, chute and tray materials | set | 150–350 | Lightweight plastic/plywood flap with guarded linkage; geometry depends on item dimensions. |
| 13 | Diffuse inspection light | set | 150–400 | LED strip/ring/light bar plus diffuser; keep its power path separate from signal wiring. |
| 14 | LEDs, resistors, buttons, buzzer (optional) | set | 100–300 | Green PASS, red FAIL, amber UNVERIFIED; add manual acknowledge/reset button if desired. |
| 15 | Latching stop switch, fuse, holder and wiring | set | 250–600 | Motor power must be physically disconnectable. Select fuse to protect wiring and suit measured load; do not guess fuse value. |
| 16 | Sensor/camera brackets, cable clips, guards | set | 200–500 | Protect the camera position and cover pinch points without blocking the view. |

**Initial expected spend:** approximately **₹3,900–₹9,000** if most mechanical parts are purchased new. A practical target of **₹4,500–₹6,500** is possible if the frame, tray, belt and mounts can be made from spare/recycled material. Laptop, phone, tools, shipping and replacement parts are excluded. These estimates intentionally include a contingency because the motor/driver and mechanical design are not frozen.

### Price references (for orientation, not endorsements)

- ESP32 DevKit and low-cost sensor/motor catalog examples: RoboForge components catalogue — https://www.roboforge.in/components (shown examples include ESP32 DevKit ₹449 and IR sensor ₹45).
- MG996R-class servo example: AM Electronics — https://amelectronics.in/shop/ (listed example ₹295 incl. GST); RoboForge also showed an MG996R-class servo around ₹299.
- Low-RPM geared motor example: AM Electronics — https://amelectronics.in/shop/ (listed 10 RPM, 12 V low-noise motor around ₹195). Listing price does not establish torque/current suitability.
- 12 V, 5 A adapter example: Robocraze — https://robocraze.com/products/kento-g-12v-power-adapter-5a-60w-with-5-5mm-dc-plug-standard-ac-to-dc-power-supply (displayed ₹429 when checked; stock can change).
- BTS7960 driver example: Robocraze — https://robocraze.com/products/bts7960b-43a-h-bridge-motor-driver (displayed ₹316 when checked, but was shown sold out; only a price reference, not a selected part).

## 4. Mechanical requirements

### 4.1 Frame and belt

- Keep the prototype on a stable table; add feet or clamps so the rig cannot walk during operation.
- Make the drive roller and idler roller parallel. The belt should run centrally without rubbing the frame.
- Provide a simple tension adjustment using slotted mounts on the idler roller.
- Cover roller/drive pinch points. Do not run fingers near the belt while powered.
- Keep a removable catch tray under or beside the reject side so rejected items cannot fall onto wiring.
- Ensure the object does not roll, tip, or rotate unpredictably while the belt stops.

### 4.2 Motor and roller selection

Choose the motor only after a rough load test. Establish the desired belt speed, item mass, roller diameter, and whether the conveyor must start while loaded. For a roller diameter `D` in mm and motor output speed `N` in RPM, the ideal belt speed is approximately:

`belt speed (mm/s) = π × D × N / 60`

This is an ideal estimate; real speed falls under load and depends on belt slip. A 30 mm roller at 10 RPM yields about 15.7 mm/s ideally. Start slowly. Measure the motor's rated current and, preferably, stall current from a trustworthy datasheet; if stall current is unavailable, use a current-limited bench supply or safe measurement method rather than assuming it is small.

**Driver gate:** Do not buy or wire the motor driver until the exact motor voltage and current are known. Select a driver whose documented continuous output rating, thermal behaviour, input logic, and transient handling suit that motor. A module advertised with a very high peak current does not necessarily sustain that current without heatsinking/cooling.

### 4.3 Reject mechanism

Use a servo to move a small flap between a neutral/pass-clear position and a reject position. The belt must be stopped before the flap moves. Keep the linkage lightweight; use a hard stop and mount the servo so the linkage cannot overtravel into the belt. Initially validate the mechanism using paper/cardboard placeholders, then light inert test objects. Do not test with sharp, hot, fragile, heavy, or hazardous parts.

## 5. Electronics architecture

```text
POWER FLOW
12 V DC adapter -> fuse + latching stop -> motor driver -> DC geared motor
12 V DC adapter -> regulated 5-6 V supply -> servo (reject flap)

CONTROL FLOW
Phone camera -> laptop/PC running local inference
Laptop/PC <-> ESP32 (Wi-Fi or USB serial)
Presence sensor -> ESP32
ESP32 -> motor-driver signals, servo signal, green/red/amber status LEDs

Power note: follow the selected modules' datasheets. Join signal grounds where required,
but never route motor current through the ESP32 board or a solderless breadboard.
```

The stop switch must remove power from the conveyor drive path. Software stop and dashboard buttons are not substitutes for a physical power disconnect. A future safety-rated industrial system requires a separate engineering review and appropriate certified safety controls.

## 6. Provisional ESP32 signal map

This map is an initial proposal for a common ESP32 DevKit, not a universal pinout. Confirm the exact board schematic and avoid boot-strapping pins or pins reserved by attached peripherals on the board you purchase.

| Signal | Proposed GPIO | Notes |
|---|---:|---|
| Presence sensor digital output | GPIO 34 | Input-only on classic ESP32; it has no internal pull-up/down. Add the appropriate external bias or choose another pin if required. Ensure sensor output never exceeds 3.3 V. |
| Motor driver PWM/enable | GPIO 25 | Only if required by the chosen driver; otherwise adapt to its interface. |
| Motor direction input A | GPIO 26 | Driver-dependent. |
| Motor direction input B | GPIO 27 | Driver-dependent. |
| Servo PWM signal | GPIO 18 | Servo power must come from its regulated external supply. |
| Green PASS LED | GPIO 16 | Use a series resistor or a suitable transistor/driver circuit. |
| Red FAIL LED | GPIO 17 | Use a series resistor or a suitable transistor/driver circuit. |
| Amber UNVERIFIED LED | GPIO 19 | Use a series resistor or a suitable transistor/driver circuit. |
| Optional acknowledge button | GPIO 23 | Configure with a safe pull-up/down matching the wiring. Debounce in firmware. |
| USB programming/logs | USB port | Keep USB connected to the laptop for development; it may also serve as a serial link in an early version. |

GPIO logic is **3.3 V**, not 5 V tolerant. Do not connect a 5 V sensor output directly to an ESP32 input. Verify sensor module output type, driver logic requirements, PWM frequency, and servo pulse requirements before wiring.

## 7. Power budget and electrical rules

The power supply must be selected from actual component data, not by adding nominal labels loosely. Consider motor start/stall current, servo peak current, light load, and margin. A 12 V, 5 A adapter is a useful candidate for a small rig, but is not approved until the selected motor's current and startup behaviour are checked.

- Power the ESP32 via USB during early development.
- Power the motor through the selected motor driver, with the correct voltage/current rating and suitable wiring.
- Power the servo from its own regulated 5–6 V supply sized for its peak load. Share signal ground with ESP32 if the servo/driver signal reference requires it.
- Do not use a solderless breadboard for motor current or servo power distribution.
- Use insulated screw terminals/connectors, appropriate wire gauge, strain relief and a fuse close to the DC source.
- Do not connect/disconnect the motor while the power system is energised.
- Keep motor/servo wires away from sensor and camera cables; twist motor supply leads if noise is a problem.
- Confirm DC polarity with a meter before connection.
- If the driver/motor becomes hot, smells, vibrates unexpectedly or draws excessive current, disconnect power and diagnose before continuing.

## 8. Physical controls and safety checklist

Minimum physical provisions:

- Latching stop or clearly accessible DC power disconnect for the conveyor drive.
- Main adapter unplug access without reaching over moving parts.
- Guards over the belt/roller pinch points and reject linkage.
- Stable mount, cable strain relief, insulated terminals and a fuse on the DC supply path.
- No exposed mains wiring. Use a commercially enclosed adapter.
- Clear mark: **TABLETOP PROTOTYPE — NOT FOR INDUSTRIAL OR HUMAN-SAFETY USE**.

The prototype is intended for supervised bench use only. Keep hair, sleeves, jewellery and fingers away from rollers and the reject linkage. The reject action must not occur while a hand is placing an object. Only the dedicated physical stop can be relied on to remove motor drive power.

## 9. Build sequence

### Stage A — Mechanical mock-up (no powered motor)
1. Cut and assemble the frame/base.
2. Install two rollers and verify they are parallel and rotate freely.
3. Fit the belt and create tension adjustment.
4. Install motor mount, servo bracket, reject flap and catch tray without energising anything.
5. Add guards and verify the flap cannot touch the belt or pinch a finger.

### Stage B — Electronics on the bench (mechanics still unpowered)
1. Identify the exact ESP32, sensor, motor driver and servo model numbers.
2. Read their datasheets/module markings and record voltage, logic and current limits.
3. Test ESP32 USB programming and LED outputs only.
4. Test sensor output and confirm it is safe for 3.3 V GPIO.
5. Test the servo on its correct external supply, with no linkage attached; confirm idle position and range.
6. Test the motor driver with the motor mechanically unloaded, current-limited if possible, and the stop switch in the circuit.

### Stage C — Integrated movement
1. Connect the motor to the conveyor only after driver and current compatibility are confirmed.
2. Verify direction at the lowest practical speed and confirm stop action.
3. Test the presence sensor repeatedly with the belt stopped.
4. Run the belt at low speed with no object; confirm alignment and no rubbing.
5. Move the object by hand first to check station spacing, camera framing and reject tray geometry.
6. Add the phone camera and light; only then connect the software decision loop.

### Stage D — Fail-safe acceptance
1. Simulate a disconnected sensor: system must not silently resume automatic handling.
2. Simulate delayed or missing laptop response: belt stays stopped or enters the documented timeout safe state.
3. Send duplicate FAIL messages: a single object must cause at most one reject action.
4. Send UNVERIFIED: amber status, belt remains stopped for manual resolution.
5. Press the physical stop during a low-speed run: motor drive power must be removed.

## 10. Pre-power checklist

- [ ] Exact motor voltage and stall/rated current documented.
- [ ] Driver current/voltage capability checked against that motor.
- [ ] Servo has a suitable external regulated supply.
- [ ] Grounds and signal references are understood and correctly connected.
- [ ] No ESP32 input sees more than 3.3 V.
- [ ] Motor power does not pass through the ESP32 or breadboard.
- [ ] Fuse, latching stop/disconnect and insulated terminals installed.
- [ ] Polarity checked with a multimeter.
- [ ] Belt/roller/reject linkage pinch points guarded.
- [ ] Bench is clear of loose wires and tools.
- [ ] First powered test is performed at low speed with no item on the belt.

## 11. Decisions deliberately left open

The following must be confirmed before finalising exact dimensions, motor, driver, lighting and camera position:

1. The object category and the model's training/evaluation images.
2. Maximum item length, width, height, mass and whether it is rigid or flexible.
3. The exact ESP32 DevKit and sensor modules available locally.
4. The selected motor's datasheet/current values and matching driver.
5. Phone model/OS and supported camera-streaming method.
6. Whether reject is a side-push flap, drop flap or diverter gate.

Do not buy a large batch of mechanical parts yet. Buy the electronics only after confirming their ratings; build the frame as a simple adjustable prototype until the inspection target is chosen.

## 12. References

Prices and listings checked 15 October 2026; current stock and pricing can change.

- RoboForge, electronics components catalogue: https://www.roboforge.in/components
- AM Electronics, shop catalogue: https://amelectronics.in/shop/
- Robocraze, 12 V 5 A adapter: https://robocraze.com/products/kento-g-12v-power-adapter-5a-60w-with-5-5mm-dc-plug-standard-ac-to-dc-power-supply
- Robocraze, BTS7960 driver listing (price reference only; listed sold out at check time): https://robocraze.com/products/bts7960b-43a-h-bridge-motor-driver

---

**Document 02 exit condition:** Do not freeze the electrical BOM until the actual motor and its stall current, driver model, ESP32 board revision, and sensor output levels are documented. The next document is **Document 03 — Repository Audit & Software Architecture**.
