---
title: "Document 09 — End-to-End Integration & Verification Test Plan"
subtitle: "Agentic AI Smart Manufacturing Quality Inspection & Automation Platform"
author: "Engineering Specification"
date: "15 October 2026"
---

# Document control

| Field | Value |
|---|---|
| Document ID | MFG-QA-D09 |
| Revision | 1.0 — Initial integration plan |
| Status | Proposed test plan; execution evidence not yet recorded |
| Applies to | Supervised, low-voltage tabletop prototype using a phone camera, Linux laptop, local inference/API service, dashboard, and ESP32 controller |
| Related documents | 01 Project Charter; 02 Hardware Design & BOM; 03 Repository Audit & Software Architecture; 04 Dataset & AI Model Qualification; 05 Phone Camera & Laptop Setup; 06 ESP32 Firmware Specification; 07 Inspection API & Decision Engine; 08 Operator Dashboard Frontend Specification |

> **Status and evidence note:** This document defines the proposed verification plan. It does not claim that the full system, any test, or any performance target has already been implemented or passed. Record actual commands, build hashes, measured results, defects, and sign-offs in the test evidence log when executing the plan. The product/defect category, deployed model, score thresholds, exact hardware pins, camera, and motor driver remain release-controlled decisions until verified against the real repository and components.

# 1. Purpose and release philosophy

This plan verifies that the prototype behaves as one coherent inspection system rather than as a set of separately working components. It covers the path from an item-present signal and camera capture through image validation, model inference, deterministic decision, durable record creation, operator display, bounded ESP32 command, physical response, and final audit record.

The design is **edge-first**. A working LAN/internet connection must not be required for local inspection. Cloud sync, remote analytics, and advanced agent behavior are outside the first tabletop release unless explicitly added through a reviewed change.

The system is not a certified industrial safety controller and must not be connected to production machinery or used to make unsupervised safety-critical decisions. Initial tests must use a guarded, low-voltage tabletop rig with an accessible physical power disconnect and an operator present.

## 1.1 Core invariants

1. Every completed inspection has exactly one terminal quality outcome: `PASS`, `FAIL`, or `UNVERIFIED`.
2. Missing, stale, invalid, low-quality, or unprocessable evidence must never silently become `PASS`.
3. Quality outcome and physical action state are separate. A `FAIL` decision does not prove a reject arm moved or the item was diverted.
4. Each inspection and machine command is traceable by a stable ID. Retries must not create duplicate reject actions.
5. Persist the decision and command intent before transmitting a physical action.
6. The laptop is the decision authority. The ESP32 executes only bounded commands and reports acknowledgement/completion; it does not make AI decisions.
7. An LLM or agent may explain or summarize records but must not choose arbitrary GPIOs, motor duty cycles, servo angles, or bypass deterministic safety checks.
8. On control-service loss, serial disconnect, watchdog expiry, or invalid command, stop/hold the tabletop process in the safest prototype-defined state and require an explicit recovery path.
9. `UNVERIFIED` means unresolved evidence, not a disguised pass or fail. The default action is hold/manual review, not automatic acceptance or rejection.
10. An internet/cloud failure must not corrupt local records or disable a fully local inspection path.

# 2. System under test and interface boundaries

## 2.1 Logical path

`Presence sensor / operator trigger -> capture adapter -> frame validation -> PatchCore inference adapter -> deterministic policy -> durable local database + artifacts -> dashboard/status event -> command dispatcher -> ESP32 acknowledgement/completion -> event log`

The implementation may split these responsibilities across processes, but their contracts must remain explicit. Record the actual process boundaries and versions before running integration tests.

## 2.2 Components to identify before testing

| Component | Required evidence before test | Primary failure modes |
|---|---|---|
| Phone/webcam camera | Device path or stream URL, resolution, frame rate, focus/exposure behavior, connection mode | Missing frames, blur, glare, changed framing, disconnect |
| Capture adapter | Input source, timeout, image dimensions, capture timestamp, image hash | Stale/repeated frame, decode failure, timeout |
| Model package | Weights hash, architecture, preprocessing version, expected input shape, release ID | Missing/corrupt weights, incompatible preprocessing, inference failure |
| Decision policy | Versioned thresholds, review band if used, quality gates, boundary semantics | Threshold ambiguity, silent default, invalid score |
| API/orchestrator | API version, configuration, health/readiness behavior, timeouts | Partial request, duplicate request, worker crash |
| Local persistence | Database path, schema/migration version, artifact root, backup path | Disk full, corruption, write failure, missing artifact |
| Operator dashboard | UI build, API base URL, status mapping, review/override permissions | Stale UI, wrong badge, duplicate operator action |
| ESP32 firmware | Firmware build/hash, protocol version, serial port, command allowlist | Disconnect, malformed frame, stale ACK, reset during action |
| Conveyor/reject mechanism | Rated supply, driver model, actuator limits, emergency disconnect, mechanical guards | Jam, overtravel, power disturbance, moving-part hazard |

## 2.3 Environment manifest

Create a checked-in `test-evidence/environment.md` or equivalent containing:

- OS and kernel version; Python/runtime and package lockfile hash.
- Git commit, dirty working-tree state, build identifiers, API and UI versions.
- Model artifact path and SHA-256; preprocessing and decision-policy versions.
- Database path/schema revision and artifact-storage path.
- Camera model/device path, capture resolution, mode (USB or Wi-Fi), mounting distance, lighting and exposure settings.
- ESP32 board, firmware hash, serial settings, pin map revision, motor driver, supply voltage/current rating, servo and sensor model.
- Test object IDs and data split; never mix threshold/calibration data into the locked final test set.
- Configuration values with secrets removed. Do not commit Wi-Fi passwords, tokens, private keys, or production credentials.

# 3. Verification stages

Do not connect all components at once. Integrate in small vertical slices so the source of a fault is identifiable.

| Stage | Integration slice | Exit gate |
|---|---|---|
| S0 — Baseline | Repository, builds, configuration, schemas, firmware and model artifacts identified | Reproducible environment manifest; clean startup path documented |
| S1 — Capture | Camera -> frame validation -> stored sample | Repeated capture, timeout and invalid-frame tests pass; hashes and metadata recorded |
| S2 — Inference | Validated image -> model adapter -> raw score/map | Model loads explicitly; finite output; latency and memory measured; no hidden fallback model |
| S3 — Policy | Model output + input-quality checks -> deterministic outcome | Boundary tests pass; invalid evidence yields `UNVERIFIED`; policy version stored |
| S4 — Persistence/API | API request -> decision -> transaction -> inspection retrieval | Idempotency and crash/restart recovery pass; records and artifacts are consistent |
| S5 — Dashboard | API -> live status/history/detail/review UI | Correct state mapping; stale/error states visible; operator actions auditable |
| S6 — Controller simulation | API command dispatcher <-> simulated ESP32 | Protocol, ACK, timeout, retry and duplicate-command tests pass without motors |
| S7 — Bench I/O | ESP32 LEDs/sensor/servo, motor driver disconnected initially | Sensor and indicator mapping proven; actuator limits verified with safe test fixtures |
| S8 — Integrated tabletop | Capture -> decision -> logged action -> physical outcome | All critical end-to-end scenarios pass under operator supervision |
| S9 — Soak/recovery | Repeated cycles, injected disconnects, restart and disk/resource checks | No silent outcome changes, duplicate rejects, corrupt records, or unreconciled actions |

Advance only after the prior stage's exit evidence is recorded. If a stage is blocked, continue only with independent work that does not depend on the failed interface.

# 4. End-to-end behavior contract

## 4.1 Normal cycle

1. The presence sensor or operator requests an inspection. Assign an inspection ID and correlation ID.
2. Stop/hold the tabletop belt before capture, according to the approved mechanical sequence.
3. Capture one frame and validate decode success, dimensions, age, exposure/blur requirements if implemented, and framing policy.
4. Store the original frame or configured evidence artifact and hash it. Do not overwrite the only evidence image when generating a heatmap.
5. Run the explicitly released model/preprocessing pipeline. Reject NaN, infinity, wrong shapes, missing weights, or incomplete outputs.
6. Apply versioned deterministic policy. Produce one result: `PASS`, `FAIL`, or `UNVERIFIED`, plus typed reason codes and score metadata where available.
7. Commit inspection, events, artifact references, model release, and policy version durably.
8. For `PASS`, show green and do not request reject actuation. For `FAIL`, show red and enqueue one bounded reject command. For `UNVERIFIED`, show amber and require manual review or an explicitly configured safe hold path.
9. For any machine command, persist command intent before sending; validate command ID, target, limits and expiry; then await ACK and completion separately.
10. Persist controller response and final action state. Resume the belt only when the state machine says the next step is safe and required terminal events have been reconciled.

## 4.2 State dimensions

Do not compress unrelated state into one ambiguous status field. Track at least:

- `inspection_state`: workflow lifecycle, such as `CREATED`, `CAPTURING`, `INFERENCE_RUNNING`, `DECIDED`, `PERSISTED`, `ERROR`.
- `quality_outcome`: `PASS`, `FAIL`, `UNVERIFIED` once decided; null before decision.
- `action_state`: `NOT_REQUIRED`, `PENDING`, `SENT`, `ACKNOWLEDGED`, `COMPLETED`, `FAILED`, `UNKNOWN`.
- `review_state`: `NOT_REQUIRED`, `PENDING`, `CONFIRMED`, `OVERRIDDEN`, where supported.

The dashboard must display uncertainty explicitly. If a command was sent but no completion was received, show `UNKNOWN` or `FAILED` as appropriate; never label the object “rejected” merely because a command was enqueued.

# 5. Test strategy and data governance

## 5.1 Test layers

- **Unit tests:** pure decision policy, input validation, state transitions, protocol parser, retry policy, serialization, idempotency keys.
- **Contract tests:** API request/response schemas; firmware message schema; command allowlist; UI status mapping.
- **Component tests:** camera adapter with file/video fixtures; model adapter with known inputs; database repositories; simulated serial controller.
- **Integration tests:** API + model + database + artifact store; dashboard + API; dispatcher + simulated controller.
- **Hardware-in-the-loop tests:** sensor, lights, motor driver and servo on the guarded tabletop rig.
- **Acceptance/soak tests:** realistic item sequence, intentional faults, restart recovery, sustained repeated cycles.

Every automated test must be repeatable from a documented command. Seed random values where applicable. Test fixtures should be versioned and small enough for CI; physical tests can be recorded separately as signed evidence.

## 5.2 Dataset split rules

Use separate training, calibration/threshold-selection and locked final-test sets. Group near-duplicate images, video frames from the same physical item, and capture sessions so leakage does not make metrics artificially optimistic. Keep actual target items and defect taxonomy in a controlled dataset card. For anomaly detection, report product-level false accepts and false rejects in addition to image/pixel metrics; do not use pixel AUROC alone as proof of operational quality.

The correct anomaly threshold cannot be specified by this document. It must be derived from representative training/calibration data, locked, versioned, and evaluated against the final test set. Record the selection rationale and the cost of false accept, false reject, and `UNVERIFIED` outcomes with the responsible reviewer.

## 5.3 Repeatability and evidence

For each test case, capture: test ID, build/commit, model/policy release, input fixture or physical item ID, expected result, actual result, timestamps, logs, relevant artifact paths/hashes, pass/fail, defect ID, operator, and sign-off. Redact secrets and avoid logging unnecessary personal data.

# 6. Test case catalogue

The following cases are the minimum release suite. Expand them when concrete hardware, camera, model, and API schemas are fixed. “Expected” means required behavior, not a claim that the test has already passed.

## 6.1 Capture and input quality

| ID | Scenario | Method / stimulus | Expected result |
|---|---|---|---|
| CAP-01 | Valid frame | Capture a correctly framed reference item | Decodable image and timestamp/hash recorded; workflow proceeds |
| CAP-02 | Camera absent at startup | Start service with camera disconnected | Readiness indicates camera unavailable; inspection returns a typed failure/`UNVERIFIED`, never `PASS` |
| CAP-03 | Camera disconnect during capture | Unplug/stop stream while capture is pending | Timeout is bounded; belt remains held; reason code and event persisted if storage is available |
| CAP-04 | Corrupt/unsupported image | Submit invalid bytes or unsupported encoding | Validation rejects image; no model call; no false `PASS` |
| CAP-05 | Too-small/wrong dimensions | Submit image outside configured size constraints | Reject or return `UNVERIFIED` with explicit reason |
| CAP-06 | Stale/replayed frame | Use an expired capture timestamp or duplicate frame ID against replay policy | Reject or explicitly flag; do not treat as a fresh inspection silently |
| CAP-07 | Blur/glare/occlusion | Present intentionally poor capture | If a validated quality gate exists, mark `UNVERIFIED`; otherwise document limitation and block release until disposition |
| CAP-08 | Lighting/frame shift | Change lighting, distance and orientation within the test envelope | Record outcome and capture metadata; no hidden preprocessing or camera auto-mode changes |

## 6.2 Model and deterministic policy

| ID | Scenario | Method / stimulus | Expected result |
|---|---|---|---|
| MOD-01 | Model startup | Load exact released weights and preprocessing configuration | Ready only after a health check inference succeeds |
| MOD-02 | Missing/corrupt weights | Rename or corrupt model artifact in test environment | Readiness fails; inspection does not fall back to a different model silently |
| MOD-03 | Invalid inference output | Inject NaN, infinity, invalid dimensions or missing score/map | Typed inference error; outcome cannot be `PASS` |
| MOD-04 | Policy lower boundary | Test just below, exactly at, and just above every configured threshold | Exact comparison semantics match documented versioned policy |
| MOD-05 | Review band | Test inside the configured uncertainty/review band if configured | `UNVERIFIED` and manual-review path; no automatic accept/reject by default |
| MOD-06 | Policy/model mismatch | Configure a policy requiring an incompatible model release | Readiness or inspection rejects the incompatible combination |
| MOD-07 | Reproducibility | Run the same fixture repeatedly under identical versions/config | Results are stable within documented tolerance; deviations investigated |
| MOD-08 | Distribution stress | Evaluate held-out items, backgrounds, orientation and relevant defect examples | Metrics and failure examples recorded; no performance claim from a small demo alone |
| MOD-09 | Threshold change | Attempt to edit a threshold without producing a new policy version | Change denied or forces a versioned, auditable policy update |

## 6.3 API, persistence and recovery

| ID | Scenario | Method / stimulus | Expected result |
|---|---|---|---|
| API-01 | Valid inspection request | Submit valid request with unique idempotency key | One inspection record and stable retrieval ID created |
| API-02 | Duplicate client retry | Repeat same request/key after timeout | Same logical inspection returned; no duplicated actuator intent |
| API-03 | Conflicting idempotency key | Reuse a key with materially different request content | Conflict response; original record unchanged |
| API-04 | Missing required field | Omit source, ID or required metadata | Structured validation error; no model or machine action |
| API-05 | Unsupported API version | Call unsupported version path/header | Explicit version error; no silent schema coercion |
| API-06 | Database write failure | Use read-only/full test DB or inject transaction failure | No success response before durable commit; belt remains held; error observable |
| API-07 | Crash after decision before commit | Terminate process at an injected boundary | No partial “completed” record; recovery reconciles or marks the inspection interrupted |
| API-08 | Crash after command intent before send | Restart between DB commit and serial write | Command resumes only through idempotent dispatcher; at most one physical action per command ID |
| API-09 | Crash after send before ACK | Drop ACK then restart | Query/reconcile command where possible; do not blindly replay a non-idempotent reject action |
| API-10 | Disk full/artifact write fails | Use constrained test partition | Inspection does not claim success without required evidence persistence; safe hold and actionable error |
| API-11 | Database restart/reopen | Restart service with stored records | Prior records remain queryable and internally consistent |
| API-12 | Artifact missing/corrupt | Remove or alter stored test artifact | Integrity check detects mismatch; UI shows evidence unavailable; decision history is not silently rewritten |
| API-13 | Local-only operation | Disable internet; keep LAN/USB links needed by rig | Core local inspection continues without cloud dependencies |

## 6.4 ESP32 protocol and machine actions

| ID | Scenario | Method / stimulus | Expected result |
|---|---|---|---|
| MCU-01 | Handshake/version mismatch | Connect wrong protocol version or random serial text | Controller refuses actionable commands; explicit incompatible status |
| MCU-02 | Malformed/oversized message | Send broken JSON, truncated line and oversize payload | Parser recovers safely; no actuation occurs |
| MCU-03 | Unknown command | Submit unlisted command/action | Rejected with typed error; motor/servo state unchanged |
| MCU-04 | Out-of-range parameter | Submit invalid duration/target/servo parameter | Rejected by controller and dispatcher; no clamping into an unintended action |
| MCU-05 | PASS behavior | Complete a known `PASS` inspection | Green indication; no reject command sent; conveyor resumes only via state machine |
| MCU-06 | FAIL behavior | Complete a known `FAIL` inspection | Red indication; at most one reject command for inspection; action completion tracked separately |
| MCU-07 | UNVERIFIED behavior | Force a camera/model/quality fault | Amber/manual-review indication; no reject or pass action by default |
| MCU-08 | Duplicate command ID | Send same reject command twice | Second request is idempotently acknowledged or rejected as duplicate; no second reject cycle |
| MCU-09 | Delayed/stale ACK | Inject delayed ACK/completion from an earlier command | Correlate by command ID; ignore as current completion; action remains unresolved until reconciled |
| MCU-10 | Serial disconnect mid-cycle | Disconnect controller during commanded action | Dispatcher times out, records `UNKNOWN`/failed state, holds process and requires reconciliation |
| MCU-11 | MCU reset/watchdog | Reset controller during a safe test | Outputs boot to defined safe states; handshake required before accepting commands |
| MCU-12 | Sensor stuck/noisy | Hold sensor active or pulse it rapidly | Debounce/edge logic prevents uncontrolled repeated inspections; faults visible |
| MCU-13 | Power-up/reset test | Cycle low-voltage supply with motor power disabled, then under approved test | No unintended motion or reject pulse during boot/reset; repeatable safe outputs |

## 6.5 Dashboard and operator workflow

| ID | Scenario | Method / stimulus | Expected result |
|---|---|---|---|
| UI-01 | Outcome display | Feed one each of PASS, FAIL and UNVERIFIED from API fixtures | Correct wording/color/icon and reason displayed; color is not sole distinction |
| UI-02 | Action pending | Delay controller completion after a FAIL | UI says action pending/unknown, not “rejected successfully” |
| UI-03 | API offline | Stop API while dashboard open | Clear disconnected/error state; stale data labelled stale; no optimistic success |
| UI-04 | Review required | Create UNVERIFIED inspection | Manual review path available; review identity/reason and timestamp persisted |
| UI-05 | Override audit | Perform permitted operator override in test mode | Original model outcome remains immutable; override is a separate event with actor and reason |
| UI-06 | Duplicate click | Double-click a review or command control | One logical request/action; pending state disables or idempotently guards repeated submission |
| UI-07 | History/detail consistency | Compare list card, detail page and stored record | IDs, outcome, model/policy versions, timestamps and action state agree |
| UI-08 | Evidence render failure | Make heatmap/artifact unavailable | Error disclosed; original decision and status remain accurate |

## 6.6 Security and robustness

| ID | Scenario | Method / stimulus | Expected result |
|---|---|---|---|
| SEC-01 | Network binding | Inspect listener addresses and firewall rules | Service binds to loopback or explicitly trusted LAN only; no unintended public exposure |
| SEC-02 | Upload limits | Submit oversized, malformed or misleading MIME/file requests | Request bounded and rejected safely before costly inference |
| SEC-03 | Path traversal | Request artifact paths using `../` or encoded variants | Only authorized artifacts are accessible; no arbitrary file reads |
| SEC-04 | Command injection | Send shell metacharacters and unexpected command fields | Input remains data; no shell execution or arbitrary serial command |
| SEC-05 | Sensitive logs | Submit tokens/secret-like values in test fields | Secrets are not echoed in logs or retained unnecessarily |
| SEC-06 | Resource exhaustion | Burst requests and large image submissions under a controlled test | Limits/back-pressure prevent unbounded queue growth; faults are observable |
| SEC-07 | Clock/timestamp anomaly | Run test with invalid or shifted timestamps | IDs remain unique; recorded timestamps and monotonic duration measurement are not confused |
| SEC-08 | Untrusted agent output | Feed prompt-injection-like content through notes or artifact metadata | Agent output cannot alter policy, authorize actions, or bypass typed API validation |

# 7. Hardware safety and controlled test procedure

Before powering actuators, complete a component-specific wiring review against the actual motor-driver, servo and ESP32 datasheets. Pin numbers in earlier documents are provisional until verified on the physical board. Never power a motor or servo directly from an ESP32 GPIO. Use appropriately rated supplies, common reference where required by the driver design, fusing/current limiting, strain relief, insulation, and a physical power disconnect.

**Test sequence:**

1. Disconnect motor power and mechanically unload/remove the reject linkage. Verify controller boot, serial protocol, LED mapping and sensor readings.
2. Verify driver enable/disable behavior with motor supply disconnected. Confirm reset and cable removal do not produce an enable pulse.
3. Exercise the servo without an object in the travel path; verify physical endpoints against the linkage and firmware limits. Do not use an assumed angle as a safe value; calibrate to the installed mechanics.
4. Test the motor unloaded or with a safe low-speed setup, using the rated driver and supply. Confirm direction, stop response, heating and current behavior.
5. Fit mechanical guards and keep hands clear. Use dummy items and a spotter/operator at the physical disconnect for all moving-belt tests.
6. Test PASS, FAIL and UNVERIFIED cycles at low speed. Verify at most one reject cycle for a FAIL, and no reject pulse for PASS or the default UNVERIFIED policy.
7. Inject API disconnect, serial disconnect, camera failure, model failure and restart only under a controlled test setup. Confirm the process stays in its explicitly documented safe/held state.
8. Record wiring/pin map revision, supply ratings, operator, test video/photos where appropriate, and any abnormal heat/noise/jam. Stop immediately if wiring is uncertain, components overheat, the belt can pinch fingers, or outputs behave unexpectedly.

This is a supervised tabletop test protocol, not a substitute for a certified risk assessment, guarding design, safety relay, emergency-stop circuit, or machinery conformity process.

# 8. Performance and reliability measurements

Do not invent target latency or throughput before measuring the real laptop, camera mode, model, input dimensions, and storage. Establish a baseline by collecting a sufficiently large set of representative cycles and report at least median, p95 and maximum for relevant stages:

- capture acquisition and image validation;
- model inference and heatmap generation;
- decision-policy execution;
- durable record/artifact commit;
- command dispatch, ACK and physical completion;
- total trigger-to-decision and trigger-to-safe-next-cycle time.

Also record CPU and memory peaks, disk writes, queue depth, camera frame age, timeouts, controller reconnect time, and count of `UNVERIFIED` decisions. Define numeric acceptance targets only after the first baseline and product-cycle requirement are known. Freeze targets before the final acceptance run; do not redefine them after seeing results to make a failing build pass.

For soak tests, choose a repeat count and duration appropriate to the prototype run, then record every cycle. Minimum observations should include unique inspection IDs, unique action IDs, record/artifact consistency, failed and retried requests, service restarts, controller disconnects, and any unexplained state transition. A test run with missing evidence is incomplete, not a pass.

# 9. Fault recovery and reconciliation

## 9.1 Recovery table

| Fault | Required immediate behavior | Recovery behavior |
|---|---|---|
| Camera not ready | Prevent a decision from being inferred from stale input | Reconnect, verify fresh frame, create a new inspection or resume only if lifecycle explicitly permits |
| Model unavailable | No `PASS`; hold/stop process | Restore verified model and readiness check; preserve failed attempt evidence |
| DB/artifact storage unavailable | Do not claim durable success; hold the process | Restore storage, run integrity checks, reconcile interrupted inspections |
| Dashboard/API connection lost | Dashboard clearly shows offline/stale; controller safety independent of browser | Reconnect and refresh authoritative state from API |
| ESP32 disconnect before command | Do not send or mark action complete | Reconnect, handshake/version check, then dispatch only safely retryable pending commands |
| ESP32 disconnect after action send | Mark action `UNKNOWN` until reconciled; do not blindly resend a non-idempotent movement | Inspect controller/physical position, reconcile by command ID and operator confirmation if needed |
| Duplicate trigger | Deduplicate within documented trigger window/idempotency contract | Return linked prior inspection or create new one only under an explicit fresh-event policy |
| Power restart | Defined boot state; no spontaneous motion | Re-establish identity/version, restore persisted workflow, reconcile every nonterminal command before motion resumes |
| Corrupt/missing artifact | Surface evidence integrity failure | Preserve record and error event; reacquire only as a new inspection, not overwrite history |

## 9.2 Restart reconciliation algorithm

On service startup: (1) open database and apply reviewed migrations; (2) verify storage permissions and integrity; (3) load the explicit model/policy release; (4) establish camera and controller readiness independently; (5) query all inspections in nonterminal workflow states and all commands not known complete; (6) mark stale capture/inference work interrupted unless safe replay is explicitly supported; (7) reconcile physical commands by command ID and controller state where available; (8) mark any unprovable outcome as `UNKNOWN`/manual reconciliation; (9) enable new motion/inspection cycles only after required subsystems and safe-state checks pass.

Never infer that a reject was not performed just because its ACK is missing. Missing ACK after a physical action can be ambiguous; blindly replaying can reject the next item.

# 10. Defect severity and release gates

| Severity | Definition | Release consequence |
|---|---|---|
| S0 — Safety critical | Unexpected motor/servo motion, unsafe boot state, ignored stop, hazardous exposed motion | Stop testing immediately; release blocked until root cause and re-test signed off |
| S1 — Integrity critical | False `PASS` on missing/invalid evidence, wrong object-to-result association, duplicate reject, lost/corrupted decision record | Release blocked |
| S2 — Major | Core workflow unavailable, incorrect status/action display, unrecoverable API/controller integration failure | Release blocked for the affected operating mode |
| S3 — Moderate | Recoverable usability or observability issue with safe workaround | Acceptance owner must explicitly approve or defer before release |
| S4 — Minor | Cosmetic issue with no material safety, quality, integrity or usability impact | May be deferred with tracked issue |

## 10.1 Prototype release checklist

A build is eligible for supervised prototype demonstration only when all conditions below are evidenced:

- [ ] Environment manifest, build versions, model hash and policy version are recorded.
- [ ] All S0 and S1 defects are closed; no unexplained motion or status transitions remain.
- [ ] Camera unavailable, invalid frame, model unavailable and persistence failure cannot produce `PASS`.
- [ ] Threshold boundary and `UNVERIFIED` behavior are covered by automated tests.
- [ ] Every inspection can be retrieved with outcome, reasons, model/policy version and evidence references.
- [ ] Decision persistence precedes command transmission; retries do not duplicate the physical reject action.
- [ ] PASS, FAIL and UNVERIFIED LED/action behavior passes bench tests.
- [ ] Command intent, acknowledgement and physical completion are distinct states.
- [ ] Startup/reset/disconnect tests prove the documented safe states on the actual hardware.
- [ ] Dashboard communicates offline, stale, pending, unknown and failed states accurately.
- [ ] Local operation is verified without internet access.
- [ ] Performance values are measured; numeric acceptance limits are agreed and locked for the run.
- [ ] Operator procedure, physical disconnect, guards and test fixture are in place.
- [ ] Acceptance evidence and known limitations are signed by the responsible project owner.

Passing this checklist qualifies only the defined tabletop configuration and test envelope. It does not certify production-line readiness, broad defect coverage, industrial safety, or reliability at manufacturing scale.

# 11. Evidence repository and reporting format

Suggested structure:

```text
/test-evidence
  environment.md
  test-plan-version.txt
  automated/
    unit-test-report.xml
    coverage-summary.txt
    api-contract-report.json
  model/
    dataset-card.md
    locked-test-metrics.json
    failure-cases/
  hardware/
    wiring-review.md
    bench-test-log.csv
    photos/
    videos/
  integration/
    run-YYYY-MM-DD-NN.md
    logs-redacted/
  defects/
    defect-register.csv
```

Each run report should include: run ID/date, operator, tested build, model and policy release, hardware configuration, test IDs executed, pass/fail/blocked counts, performance summaries, deviations, defects opened/closed, evidence links/hashes, and explicit sign-off. Store only redacted logs. Protect original test evidence from silent edits; corrections should be appended or versioned.

# 12. Recommended execution order

1. Identify the actual repository and map its modules to the interfaces in Documents 03, 06, 07 and 08. Replace proposed endpoint/message names with actual contract names where they differ.
2. Implement automated unit/contract tests for policy boundaries, state machine, idempotency and firmware protocol before connecting moving hardware.
3. Complete capture/model/persistence integration using saved image fixtures and simulated controller responses.
4. Complete dashboard contract tests against known API fixture records.
5. Test ESP32 LEDs/sensor/serial behavior with motor power disconnected.
6. Add servo movement, then conveyor movement as separate controlled steps after hardware review.
7. Run full end-to-end PASS, FAIL and UNVERIFIED cycles with dummy items.
8. Inject failure and restart scenarios; reconcile every ambiguous action.
9. Lock the acceptance configuration and thresholds, execute the repeatable test suite, and publish the evidence report.
10. Review all known limitations before any external demo. Do not present simulated outputs or unverified model performance as validated manufacturing results.

# Appendix A — Test result template

| Field | Entry |
|---|---|
| Test ID / run ID |  |
| Date / operator |  |
| Git commit / dirty state |  |
| Model release / weights hash |  |
| Decision policy version |  |
| Hardware / firmware version |  |
| Preconditions and test item |  |
| Expected result |  |
| Actual result |  |
| Pass / Fail / Blocked |  |
| Latency and resource measurements |  |
| Log/artifact paths and hashes |  |
| Defect ID / severity |  |
| Notes and sign-off |  |

# Appendix B — Decisions required before the final locked run

- Final product category and documented defect taxonomy.
- Actual model weights, training provenance, preprocessing and threshold policy.
- Whether blur/glare/framing quality gates are implemented and qualified.
- Camera device and capture mode; acceptable resolution, focus and lighting envelope.
- Actual ESP32 board, firmware pin map, driver, supply, actuator limits and sensor logic.
- Exact command/ACK/completion protocol, timeout and safe-state behavior.
- Numeric latency/throughput targets derived from measured baseline and conveyor takt.
- Retention and backup policy for original images, heatmaps and operator review data.
- Named project owner and reviewer authorized to sign prototype acceptance.

---

**End of Document 09.**
