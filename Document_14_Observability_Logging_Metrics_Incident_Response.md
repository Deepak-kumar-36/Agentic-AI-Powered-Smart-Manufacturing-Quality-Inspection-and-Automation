# Document 14 — Observability, Logging, Metrics & Incident Response Playbooks

**Project:** Agentic AI Smart Manufacturing Quality Inspection & Automation Platform  
**Document type:** Engineering operations specification  
**Version:** 1.0  
**Status:** Proposed target design; implementation and current telemetry are unverified  
**Deployment target:** Local-first tabletop prototype using a phone camera, Linux/Arch workstation, local anomaly-detection inference, local persistence, dashboard, and ESP32-class low-voltage actuation.

---

## 1. Purpose

This document defines how the platform should expose its runtime state, preserve useful evidence, detect faults, and guide operators through recovery. It connects observability across the capture path, model runtime, deterministic decision policy, database/artifact storage, dashboard/API, and ESP32.

The goal is operational diagnosability—not a wall of logs. During a fault, an operator should be able to answer:
- Which inspection or command was affected?
- What component failed, and when?
- Was a decision durably recorded?
- Was a physical action requested, acknowledged, and completed?
- Is the current item in a known state?
- Is it safe to resume, or is manual reconciliation required?

This document specifies proposed behavior. Do not assume the repository already emits these signals; inspect the code and running system first.

## 2. Operational principles

1. **One traceable inspection:** use a stable `inspection_id` and correlation ID across capture, inference, decision, persistence, dashboard, and machine action.
2. **Decision and action are distinct:** a `FAIL` result does not prove a reject actuator completed its motion.
3. **Fail closed:** invalid frame, model failure, stale result, persistence failure, incompatible versions, or ambiguous state must never silently become `PASS`.
4. **Local-first:** health, logs, metrics, and core inspection must continue without cloud access.
5. **Structured evidence:** logs explain events; metrics show trends; traces/timelines connect steps; audit records preserve consequential state changes.
6. **No secret leakage:** logs must not contain credentials, access tokens, private keys, or unnecessary raw image data.
7. **Alerts need context:** include observed value, baseline or configured limit, time window, sample count, affected component, and operator action.
8. **Recover deliberately:** never blindly replay a non-idempotent actuator command after timeout or process restart.
9. **Measure before promising:** set latency/availability targets from a measured baseline and intended use; do not invent unsupported SLOs.
10. **Prototype boundary:** this is for a supervised tabletop prototype, not a certified industrial control or safety-monitoring system.

## 3. Observability model

Use four complementary layers.

| Layer | Main question | Examples | Persistence expectation |
|---|---|---|---|
| Logs | What happened? | capture started, model exception, command ACK, config changed | Rotated local files or journal; retain incident evidence |
| Metrics | How often / how long / how much? | latency, errors, queue age, disk free, outcome counts | Local scrape/store or periodic snapshots |
| Inspection timeline / trace | Which steps belong to this item? | capture → validate → infer → decide → persist → action | Durable events keyed by inspection ID |
| Audit events | Who changed or approved consequential state? | threshold version, model release, manual review, export, restart approval | Durable, append-oriented records |

Do not require a large distributed tracing platform for the first prototype. Begin with structured logs, durable inspection events, a small metrics endpoint/exporter, and a timeline view. Introduce OpenTelemetry-compatible tracing only if it fits the actual architecture and solves a demonstrated problem.

## 4. Component map and health contracts

### 4.1 Components
- **Camera adapter:** discovers source, captures frames, timestamps them, checks dimensions/validity.
- **Inference service:** loads a specific model release, preprocesses input, computes outputs, reports latency/errors.
- **Decision engine:** validates model output and applies a versioned deterministic policy.
- **API/orchestrator:** assigns IDs, validates requests, sequences work, persists state, and orchestrates permitted machine commands.
- **Database/artifact store:** persists inspection records, events, hashes, images, heatmaps, and command history.
- **Dashboard:** reads service state and inspection history; submits authorized requests.
- **ESP32/serial bridge:** validates bounded commands and reports ACK/completion/fault states.
- **Host runtime:** OS process state, disk, memory, CPU, network/listening state, service start/stop, time synchronization.

### 4.2 Liveness vs readiness
- **Liveness:** is the process responsive enough to stay running?
- **Readiness:** can it safely perform the declared operation now?
- **Degraded:** some features are unavailable, but the limitation is explicitly shown.
- **Not ready:** core requirements are missing or inconsistent; new automatic inspections must not proceed.

Examples:
- API process is alive but model weights fail hash validation → liveness may be healthy; readiness is false.
- Dashboard can load but the database is read-only/full → dashboard may display status, but new inspection readiness is false if durable result persistence is required.
- ESP32 serial link is disconnected → software-only test mode may remain available, but hardware operation is not ready.
- Camera source is absent → readiness for camera-based inspection is false.

Health endpoints must not expose secrets, full file paths, raw environment variables, or detailed stack traces to an unauthenticated client.

## 5. Correlation and event identity

Every inspection operation should carry:
- `inspection_id`: stable identity for one item/inspection attempt.
- `request_id`: identity for one API request.
- `correlation_id`: joins related logs and events across components.
- `frame_id` and frame hash where available.
- `model_release_id` and `policy_version`.
- `machine_command_id` plus an idempotency key for any physical command.
- `boot_id` or process-instance ID to distinguish events across restarts.

Do not reuse an `inspection_id` for a different physical item. If an API client retries a request, the documented idempotency rules determine whether it is the same inspection or a new attempt. Store the timestamp and clock source used for each stage; use UTC for persisted event timestamps and make local display time explicit.

## 6. Structured logging specification

### 6.1 Format
Emit one structured JSON object per event where practical. Keep event names stable, field names consistent, and values typed.

Example (illustrative schema only):
```json
{
  "timestamp": "2026-10-15T12:34:56.789Z",
  "level": "INFO",
  "event": "inspection.inference.completed",
  "service": "inference",
  "service_version": "0.1.0",
  "boot_id": "runtime-20261015-a",
  "request_id": "req-example",
  "correlation_id": "corr-example",
  "inspection_id": "insp-example",
  "model_release_id": "patchcore-release-example",
  "duration_ms": 82.4,
  "result": "success"
}
```
Values and IDs above are placeholders. Replace them with runtime-generated identifiers; never hard-code example IDs.

### 6.2 Required common fields
- UTC timestamp with timezone.
- Severity (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` or a consistent equivalent).
- Stable event name.
- Service/component name and software version.
- Process/boot identifier.
- Correlation/request/inspection/command ID when applicable.
- Outcome/result and a typed reason/error code where relevant.
- Duration and retry number for timed operations where meaningful.

### 6.3 Event naming pattern
Use names like:
- `camera.source.connected`
- `camera.frame.captured`
- `camera.frame.rejected`
- `model.load.started`
- `model.load.failed`
- `inspection.inference.completed`
- `decision.created`
- `inspection.persist.failed`
- `machine.command.issued`
- `machine.command.acknowledged`
- `machine.command.completed`
- `machine.command.timed_out`
- `operator.review.created`
- `policy.version.changed`
- `backup.restore.completed`

Keep event names stable across releases. Put variable values into fields, not the event name.

### 6.4 Logging levels
- **DEBUG:** detailed diagnostic events useful during development; off or tightly limited during routine operation.
- **INFO:** normal lifecycle and consequential state transitions.
- **WARNING:** unexpected but contained condition, retry, degraded component, threshold crossing, or rejected input.
- **ERROR:** operation failed; affected action/inspection may need recovery.
- **CRITICAL:** integrity, security, or physical-state uncertainty requiring immediate operator attention and safe hold.

Severity definitions should be documented and applied consistently.

### 6.5 Redaction and prohibited content
Never log:
- passwords, bearer tokens, private keys, Wi-Fi secrets, or full secret-bearing environment dumps;
- raw image bytes, full camera frames, or entire heatmaps;
- personally identifying or unrelated captured material unless explicitly necessary and governed;
- arbitrary request bodies without field filtering;
- untrusted text as a raw terminal command.

Log artifact references and hashes instead of image bytes. Use allow-listed fields for diagnostic exports.

## 7. Metrics catalogue

Metrics must be low-cardinality. Do not use `inspection_id`, file paths, user-entered text, or arbitrary error messages as metric labels.

### 7.1 Inspection pipeline
| Metric concept | Type | Useful dimensions | Interpretation |
|---|---|---|---|
| Inspection requests started/completed | Counter | outcome, mode | Volume and completion rate |
| Inspections by terminal outcome | Counter | `PASS`/`FAIL`/`UNVERIFIED`, product/category when known | Outcome mix; not quality accuracy by itself |
| End-to-end inspection duration | Histogram | mode, outcome | Latency distribution from request/capture to durable decision |
| Stage duration | Histogram | stage | Capture, validation, preprocessing, inference, decision, persistence |
| Active inspections / queue depth | Gauge | queue name | Backlog and concurrency |
| Age of oldest queued inspection | Gauge | queue name | Detects stuck work |

### 7.2 Camera and frame quality
| Metric concept | Type | Dimensions | Interpretation |
|---|---|---|---|
| Frames captured / rejected | Counter | source, reason code | Source health and input rejection |
| Capture duration | Histogram | source | Camera latency |
| Frame dimensions observed | Gauge or event | source/config version | Detects configuration changes |
| Image validation failures | Counter | reason code | Blur/size/decode/brightness checks, if implemented |
| Frame age at inference | Histogram | source | Detect stale frames and slow pipelines |
| Reconnect attempts / failures | Counter | source | Unstable USB/Wi-Fi capture path |

Only publish a blur/brightness/quality metric if a defined implementation exists. A proxy is not a validated measure of image usability.

### 7.3 Model and decision engine
| Metric concept | Type | Dimensions | Interpretation |
|---|---|---|---|
| Inference duration | Histogram | model release, backend/device class | Runtime latency |
| Inference failures/timeouts | Counter | typed reason code | Model/runtime reliability |
| Model readiness | Gauge | release | 1 when required artifact/runtime checks pass, else 0 |
| Output validation failures | Counter | reason code | Missing, non-finite, stale, incompatible output |
| Anomaly score summaries | Histogram/periodic summary | release, product/config cohort | Distribution monitoring, not accuracy |
| Decisions by policy version | Counter | policy version, outcome | Detect unexpected policy/output changes |

Use a bounded set of labels. If product categories are open-ended, store them in event records and aggregate intentionally rather than exploding metric cardinality.

### 7.4 Persistence and host
| Metric concept | Type | Dimensions | Interpretation |
|---|---|---|---|
| Database operation errors | Counter | operation, typed error | Persistence reliability |
| Artifact write failures | Counter | artifact type, reason | Missing evidence risk |
| Database transaction duration | Histogram | operation | Latency/regression |
| Disk free bytes and percent | Gauge | mount/application data volume | Prevent disk-full incidents |
| Process memory/CPU | Gauge | service | Resource pressure |
| Restart count / uptime | Counter or gauge | service | Crash-loop detection |
| Clock offset / timestamp warning | Gauge/event | host | Chronology integrity |
| Backup age / last verified backup | Gauge/event | backup target | Recovery readiness |

### 7.5 ESP32 and machine-action telemetry
| Metric concept | Type | Dimensions | Interpretation |
|---|---|---|---|
| Serial connection state | Gauge | device alias | Connected/readiness |
| Commands issued / ACKed / completed | Counter | allow-listed command type, status | Tracks command lifecycle |
| Command ACK and completion latency | Histogram | command type | Firmware responsiveness |
| Command timeout / malformed reply | Counter | reason code | Reliability or protocol faults |
| Duplicate command suppression | Counter | command type | Retry visibility |
| Unreconciled machine commands | Gauge | state | Any positive value requires investigation before resume |
| Reject cycles confirmed | Counter/event | source of confirmation | Distinguishes requested from confirmed physical action |

Do not label a reject action “successful” merely because an ACK was received. ACK and physical completion/confirmation are separate states.

## 8. Service-level objectives and alert thresholds

Do not choose arbitrary uptime or latency numbers before measuring a representative baseline. Define a local operational target for each metric:
- target and measurement window;
- scope (hardware present, software-only, camera mode, product class);
- measurement method and denominator;
- exceptions/maintenance periods;
- owner and review date;
- action when breached.

For the initial prototype, establish a baseline for p50/p95/p99 stage latency, error rate, disk consumption, camera reconnection frequency, and command completion time. Then agree on limits appropriate for the demo and expected workload.

### Suggested alert conditions (thresholds configured after baseline)
- Critical: current inspection or actuator state is unknown; storage failure prevents durable inspection; model/policy integrity fails; unexpected motor/servo behavior.
- High: model unavailable during intended run; repeated inference/API failures; serial command unresolved; camera source disappears while hardware mode is armed.
- Medium: sustained latency regression, retry burst, growing queue, elevated frame rejection, disk space approaching configured minimum.
- Low: advisory score-distribution shift or non-blocking configuration warning.

Every alert includes observation, time window, affected component, known impact, relevant IDs, and first-response instruction. Avoid alerting on one isolated noisy measurement unless the consequence is inherently critical.

## 9. Inspection timeline and audit event contract

The durable inspection timeline should capture material transitions such as:
`CREATED → CAPTURING → IMAGE_VALIDATED → INFERENCE_RUNNING → DECIDED → PERSISTED → ACTION_PENDING → ACTION_ACKNOWLEDGED → ACTION_COMPLETED`.

Not every inspection has an actuator action. A safe `PASS` path may have no reject command; `UNVERIFIED` may require hold/manual review. Use explicit terminal/action states in the actual schema.

Each transition event should include:
- inspection ID and event sequence;
- UTC timestamp;
- prior state and next state;
- actor/service and software version;
- reason code and relevant version IDs;
- action/command ID where relevant;
- whether persistence succeeded.

The inspection’s visual outcome and machine-action state must be independent fields. Historical decisions should not be overwritten after manual review; record a new review/disposition event with author and time.

## 10. Dashboard and operator visibility

### Minimum status strip
- API liveness and readiness.
- Camera connected and last successful frame time.
- Model release ID and readiness.
- Active policy version.
- Database/artifact store writable state and disk free space.
- ESP32 connection and firmware/protocol identity.
- Machine mode: software-only, supervised hardware, or disabled.
- Current unresolved incident/command status.

### Minimum panels
1. **Inspection flow:** counts and outcome distribution with selected time range and denominator.
2. **Latency:** end-to-end plus per-stage p50/p95/p99.
3. **Camera quality:** frame age, validation failures, source reconnects, config revision.
4. **Model health:** release ID, load/inference failures, score distribution summary.
5. **Persistence:** DB errors, artifact write errors, free disk, backup status.
6. **Machine actions:** issued, ACKed, completed, timed out, unresolved.
7. **Review and incidents:** queue size, oldest unresolved age, severity, owner.
8. **Audit/release history:** model/policy/config changes and approvals.

Do not display a single “accuracy” value unless the ground-truth source, label quality, dataset, metric, and denominator are explicit.

## 11. Error taxonomy and response mapping

Use stable machine-readable reason codes. Illustrative set:

| Code | Meaning | Expected system response |
|---|---|---|
| `CAMERA_SOURCE_UNAVAILABLE` | Capture source not reachable | Not ready for camera inspection; no PASS |
| `FRAME_DECODE_FAILED` | Invalid/truncated frame | Reject frame; mark inspection UNVERIFIED if an inspection was started |
| `FRAME_STALE` | Frame too old or matched to wrong cycle | Do not use for decision; hold/reconcile |
| `FRAME_QUALITY_OUT_OF_RANGE` | Outside qualified image constraints | UNVERIFIED/manual review |
| `MODEL_NOT_READY` | Model missing or integrity/load check failed | Not ready; no inference decision |
| `INFERENCE_TIMEOUT` | Inference exceeded configured timeout | UNVERIFIED; no stale-result fallback |
| `MODEL_OUTPUT_INVALID` | NaN, infinity, missing score, unexpected shape | UNVERIFIED |
| `POLICY_VERSION_UNAVAILABLE` | Required policy cannot be loaded | Not ready; no default threshold |
| `PERSISTENCE_FAILED` | Durable record could not be committed | Do not report durable completion; hold item |
| `ARTIFACT_WRITE_FAILED` | Required evidence could not be written | Apply documented evidence policy; fail closed if required evidence is mandatory |
| `SERIAL_DISCONNECTED` | ESP32 link lost | Hardware mode not ready; do not send blind retry |
| `COMMAND_ACK_TIMEOUT` | No command ACK in window | Reconcile current state before retry |
| `COMMAND_COMPLETION_UNKNOWN` | ACK received but completion not confirmed | Hold sequence; operator verifies physical state |
| `DUPLICATE_COMMAND_SUPPRESSED` | Idempotency guard blocked duplicate | Record event; do not repeat action |
| `DISK_SPACE_LOW` | Configured minimum crossed | Alert; block new work cleanly before writes become unsafe |
| `CONFIG_VERSION_MISMATCH` | Incompatible capture/model/policy/firmware version | Not ready or UNVERIFIED per policy |

This table is a proposed vocabulary. Map codes to actual exception and API response types after repository inspection. Do not expose detailed stack traces to end users.

## 12. Incident severity and ownership

| Severity | Definition | Immediate response |
|---|---|---|
| SEV-1 / Critical | Physical state unknown, unexpected motion, evidence/decision integrity compromise, possible false acceptance due to system fault | Stop sequence, isolate power if necessary, prevent new automatic inspections, preserve evidence |
| SEV-2 / High | Core component unavailable, unresolved command, model/policy integrity failure, repeated persistence failure | Hold affected workflow; investigate; resume only after explicit checks |
| SEV-3 / Medium | Material degradation without known integrity compromise, growing queue, repeated noncritical frame rejection | Assign owner, inspect telemetry, apply bounded workaround |
| SEV-4 / Low | Advisory drift, isolated recoverable warning, documentation/configuration issue | Record and review in normal engineering cycle |

The person on duty may be the developer/operator for the tabletop prototype. Record one incident owner and one decision-maker for resuming hardware operations, even if those roles are held by the same person.

## 13. Incident response playbooks

### IR-01 — Camera disconnected or producing invalid frames
**Signals:** source unavailable, frame timeout, decode failure, stale frame, input-quality check failure.

1. Place the workflow in hold; disable any next-item actuation.
2. Record last successful frame time, camera source/configuration, current inspection ID, and hardware mode.
3. Confirm whether the affected frame belongs to the current physical item.
4. Check USB/Wi-Fi connection, capture process, camera permissions, resolution, focus, exposure, and lighting.
5. Capture a reference frame and run the same input-validity checks.
6. Reprocess only if the exact frame/item association is still valid and policy permits it; otherwise start a new inspection for the known item.
7. Record recovery and operator approval. If item identity or state is uncertain, mark it for manual disposition.

**Do not:** reuse the previous frame or previous item’s decision as the current result.

### IR-02 — Model load failure, inference exception, or invalid output
**Signals:** readiness false, artifact hash mismatch, timeout, exception, non-finite score, unexpected output shape.

1. Stop new automatic decisions and keep the current item in the hold/manual path.
2. Record model release ID, artifact hash, runtime version, input frame hash, and exception/reason code.
3. Verify model artifact integrity and preprocessing/runtime compatibility.
4. Do not swap to an unqualified model automatically and do not use a cached prior score.
5. Restore the last qualified release only through the release procedure.
6. Run readiness and regression tests with actuators disabled.
7. Record the approved release and resume decision.

### IR-03 — Database, disk, or artifact persistence failure
**Signals:** transaction failure, database read-only/full, artifact write error, free space below configured minimum.

1. Stop accepting new inspections that require durable evidence.
2. Keep current item held; do not label an uncommitted result as completed.
3. Record available diagnostic evidence without flooding disk.
4. Check disk usage, inode availability, permissions, database integrity, and recent backup status.
5. Free space only by documented retention policy; never delete open-incident evidence or the only copy of a required artifact.
6. Restore database writability, then verify schema/integrity and artifact references.
7. Reconcile any inspection whose transaction outcome was ambiguous; never assume it committed.
8. Run a persistence test and record approval before resuming.

### IR-04 — ESP32 serial disconnected or command status ambiguous
**Signals:** serial disconnect, malformed ACK, ACK timeout, missing completion event, command state unknown.

1. Stop the conveyor sequence and isolate motor power if physical behavior is uncertain.
2. Record inspection ID, machine-command ID/idempotency key, command type, issue time, last ACK/status, and firmware identity.
3. Do not resend the command blindly.
4. Inspect the physical item and mechanism under supervision; identify whether the action occurred, failed, or remains unknown.
5. Reconnect the expected device and validate protocol/firmware identity.
6. Query state if supported; otherwise follow the documented physical reconciliation procedure.
7. Mark the action state accurately (`COMPLETED`, `FAILED`, or `UNKNOWN/RECONCILIATION_REQUIRED`).
8. Resume only after the mechanism is in a known state and the operator records approval.

### IR-05 — An inspection returned FAIL but the item was not confirmed rejected
**Signals:** `FAIL` decision exists, but no command completion/physical confirmation exists.

1. Treat product disposition as unresolved; do not mark reject success from the model result alone.
2. Hold the line and identify the exact physical item/inspection ID.
3. Review command lifecycle and physical evidence.
4. Prevent duplicate reject cycles while state is being reconciled.
5. Have the operator manually disposition the item according to the prototype procedure.
6. Record the original model decision and a separate physical-action disposition.
7. Investigate the fault before resuming repeated automated rejects.

### IR-06 — Suspected false PASS or data/decision integrity issue
**Signals:** confirmed defect with prior PASS, unexpected threshold/policy version, artifact hash mismatch, stale result, incorrect item mapping.

1. Stop automatic inspection and preserve affected inspection IDs, image hashes, model/policy versions, timestamps, and command records.
2. Determine the suspected affected interval and whether adjacent items may be involved.
3. Keep items within that interval under manual review until scope is known.
4. Verify camera setup, frame-to-item mapping, model release, preprocessing, and threshold policy.
5. Do not relabel historical results silently; append corrected review/disposition events.
6. Run the qualified test set and compare against the last known qualified release.
7. Record root cause, affected scope, corrective action, and approval before resuming.

### IR-07 — Latency spike or growing inspection queue
**Signals:** p95/p99 stage latency increase, oldest queue age rising, timeouts, CPU/RAM pressure.

1. Check whether a physical item is waiting mid-cycle; hold safely before diagnosing.
2. Inspect per-stage duration to locate the bottleneck.
3. Check CPU, memory, thermal throttling, disk I/O, camera transport, and concurrent jobs.
4. Do not skip validation or lower the inspection standard to restore speed.
5. Reduce nonessential diagnostic work or concurrency only through a documented bounded configuration.
6. Verify stable latency and successful durable commits with actuators disabled.
7. Resume when no old result can be applied to a new item and the operator approves.

### IR-08 — Unexpected listener, credential exposure, or unauthorized configuration change
**Signals:** service bound to unintended interface, secret in logs/repository, unknown policy/model change, unexplained access failures.

1. Disable remote access and hold hardware mode if inspection integrity could be affected.
2. Preserve relevant logs and configuration hashes.
3. Rotate exposed credentials and revoke unnecessary access.
4. Verify startup binding, authorization, file permissions, release manifests, and source history.
5. Restore known-good configuration/artifacts after integrity checks.
6. Run security/integration tests before re-enabling access or actuation.
7. Document the incident and assess whether any inspection results require review.

### IR-09 — Clock drift or inconsistent event chronology
**Signals:** timestamps move backward, impossible stage durations, mismatch between host and captured event time.

1. Preserve raw timestamps and clock source; do not rewrite history to make it look consistent.
2. Check host time synchronization, time zone, and firmware timestamp source.
3. Use monotonic clocks for within-process duration measurement and UTC timestamps for persisted event time.
4. Reconstruct event order using sequence IDs and acknowledged state transitions where possible.
5. Mark chronology uncertainty in the incident record and review decisions where ordering affects item association.
6. Correct time configuration and verify before resuming.

## 14. Restart and recovery safety checklist

Before restart:
- [ ] Determine whether an item is on the conveyor or held at the inspection/reject point.
- [ ] Resolve or explicitly mark every in-flight inspection and machine command.
- [ ] Preserve logs, event sequence, command IDs, and relevant artifact hashes.
- [ ] Verify whether the last operation committed to the database.
- [ ] Disable actuation while service state is being reconciled.

After restart:
- [ ] Confirm expected host/configuration and local bind address.
- [ ] Verify database/schema and disk space.
- [ ] Verify model artifact hash, model release, and policy version.
- [ ] Verify camera source and a fresh valid frame.
- [ ] Verify ESP32 device/protocol identity, but do not automatically resume motor motion.
- [ ] Query/reconcile outstanding commands and physical item state.
- [ ] Run readiness checks and a software-only/actuators-disabled smoke test.
- [ ] Record operator approval before re-arming supervised hardware operation.

## 15. Operational reporting and review cadence

### Per demo/session
- Total inspections and outcomes with denominator.
- `UNVERIFIED` reasons and manual dispositions.
- Inference and end-to-end latency percentiles.
- Camera reconnects and frame rejections.
- Database/artifact write errors and minimum disk space.
- Commands issued, ACKed, completed, timed out, and unresolved.
- Model/policy/firmware/configuration versions.

### Weekly or at an agreed engineering checkpoint
- Recurring errors and root-cause status.
- Model-score and image-quality drift advisories.
- Incident and action-item closure.
- Dependency/configuration changes.
- Backup/restore test status.
- Outstanding risks and release readiness.

A prototype report should clearly distinguish measured results from estimates, simulated data, and incomplete validation. Never present dashboard outcome mix as model accuracy without reliable ground truth.

## 16. Implementation phases

### Phase A — Correlation and structured events
- Add inspection/request/correlation/command IDs.
- Standardize event names, severity, error codes, timestamps, and redaction.
- Persist important inspection and machine-action state transitions.

### Phase B — Metrics and readiness
- Add stage latency and failure counters.
- Add camera, model, database, disk, and ESP32 health signals.
- Separate liveness, readiness, and degraded states.

### Phase C — Timeline and dashboard
- Build an inspection event timeline.
- Add operational status strip, latency charts, persistence state, unresolved commands, and incident queue.
- Label score drift separately from confirmed quality performance.

### Phase D — Alerts and playbooks
- Set thresholds from baseline measurements.
- Add critical hold conditions and actionable messages.
- Link each alert to a specific incident runbook.

### Phase E — Reliability exercises
- Inject camera loss, model load failure, disk full, database errors, serial disconnect, duplicate command, and process restart.
- Confirm records, alerts, safe hold, and recovery.
- Document gaps before the next supervised hardware demonstration.

## 17. Acceptance checklist

- [ ] One inspection/correlation ID ties together capture, inference, decision, persistence, and any machine command.
- [ ] Logs are structured, timestamped, versioned, and redacted.
- [ ] Metrics use bounded labels and do not contain high-cardinality IDs.
- [ ] Liveness and readiness are separate and reflect model/database/camera/hardware requirements.
- [ ] Inspection outcome and physical action outcome are separate.
- [ ] Unknown command or item state prevents automatic continuation.
- [ ] Critical alerts include context and a concrete first response.
- [ ] Every failed or degraded inspection path has a typed reason code.
- [ ] Restart recovery reconciles in-flight inspections and commands before actuation.
- [ ] Disk-full and persistence-failure behavior is tested.
- [ ] Camera/model/database/serial incidents have documented runbooks.
- [ ] Logs and diagnostic exports contain no secrets or unnecessary image bytes.
- [ ] Latency/availability thresholds are justified by measured baseline and intended use.
- [ ] Local operation does not depend on cloud observability.
- [ ] Operators can identify the active model release, policy version, firmware identity, and machine mode.

## 18. Open decisions

Resolve after repository and deployment inspection:
- Existing logger, API framework, database, and service startup mechanism.
- Whether a dedicated metrics endpoint or local time-series store is needed.
- Exact metric names and instrumentation support.
- Expected demo workload and latency acceptance targets.
- How physical reject completion is confirmed on the tabletop device.
- Which event records are durable and append-only.
- Alert delivery method if the operator is away from the dashboard.
- Log retention, disk budgets, and diagnostic export controls.
- Time source and stable device identity approach.
- Who can approve restart after an incident.

## 19. Final rule

Observability must make the system’s real state clearer, not make an uncertain state look healthy. If the platform cannot establish which item was inspected, whether the result was durably recorded, or whether a physical action completed, it must hold the workflow, preserve evidence, and require explicit reconciliation before resuming.
