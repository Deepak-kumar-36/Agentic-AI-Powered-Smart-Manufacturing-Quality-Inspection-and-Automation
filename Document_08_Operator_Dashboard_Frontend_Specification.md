# Document 08 — Operator Dashboard & Frontend Specification
**Project:** Agentic AI Smart Manufacturing Quality Inspection & Automation Platform  
**Document type:** UI/UX and frontend engineering specification  
**Status:** Proposed design — actual repository and UI implementation are not yet verified  
**Version:** 1.0

## 1. Purpose

Define the operator-facing interface for the tabletop manufacturing quality-inspection prototype. The dashboard must make the current camera state, inspection result, evidence, physical action status, and any fault understandable at a glance. It should guide an operator through normal operation and safe recovery without hiding uncertainty.

This is a target design, not evidence that any page, component, API integration, or styling already exists in the repository. Confirm the actual framework and design system before implementation.

## 2. Product and operator goals

The operator should be able to:
- confirm the camera, model, local database, and controller status before starting;
- see the live camera feed and understand whether a frame is being processed;
- distinguish PASS, FAIL, and UNVERIFIED without relying on color alone;
- inspect the anomaly heatmap and model evidence when available;
- determine whether an actuator command was requested, accepted, completed, failed, or remains unknown;
- find a previous inspection, its model/policy versions, and its event history;
- resolve an item requiring review with a reason and an auditable operator identity;
- stop automatic actuation and recover from common faults using explicit, guarded controls;
- continue inspecting locally when cloud services are unavailable.

## 3. UX principles

1. **Decision first, evidence immediately available:** show the outcome and reason near the camera/result.
2. **Uncertainty is explicit:** UNVERIFIED is a first-class result, not an error hidden in a toast.
3. **Decision is not physical outcome:** a FAIL decision and an actual reject cycle have separate labels and status.
4. **No color-only semantics:** pair all status colors with text, icons, and accessible labels.
5. **Operator control over automation:** display automatic/review-only mode, and make it clear when actuation is disabled.
6. **Safe defaults:** unknown component status, stale data, or ambiguous command completion must never appear healthy.
7. **Local-first:** the primary workflow must not require cloud login or remote APIs.
8. **Auditability:** meaningful operator actions require a reason and create an event.
9. **Calm visual hierarchy:** avoid ornamental animation, gradients, glassmorphism, excessive cards, and noisy charts.
10. **Accessible and usable:** keyboard navigation, visible focus, readable type, semantic controls, and responsive layout.

## 4. Information architecture

Primary navigation:
- **Live Inspection** — default route and central operating screen.
- **Inspection History** — searchable, filterable list of completed and incomplete inspections.
- **Review Queue** — items awaiting human resolution.
- **System Status** — camera, inference, storage, serial connection, ESP32, actuator readiness, and recent faults.
- **Settings** — explicitly controlled configuration for camera, thresholds/policy selection, operating mode, retention, and service options. Calibration changes require elevated permissions and a new policy version.
- **About / Diagnostics** — application, model, policy, and firmware versions plus sanitized diagnostic export.

Do not make important controls accessible only through a hidden settings menu. The current operating mode, automatic-actuation state, and fault/stop state must remain visible on the live screen.

## 5. Live Inspection screen

### 5.1 Desktop layout

Recommended layout for a laptop screen:
- **Header:** application name, current mode, local/online status if relevant, global fault indicator, and stop/disable status.
- **Left/primary region:** large camera preview with camera label, live/stale indicator, capture controls, and optional detection/heatmap overlay.
- **Right/result region:** latest decision, reason codes, confidence/score terminology, inference duration, model/policy identifiers, and action state.
- **Bottom region:** latest inspection summary and recent events, with links to full history.
- **Persistent status strip:** camera, model, database/storage, serial/ESP32, and actuator readiness.

Use a two-column layout on typical laptop widths. On smaller screens, stack the camera and result vertically; keep the main outcome and current safety state visible without horizontal scrolling. Do not make a small phone UI the primary control surface for a moving prototype.

### 5.2 Header content

Display:
- product/system name and application version;
- selected camera and current stream state;
- operation mode: `AUTOMATIC` or `REVIEW ONLY`;
- auto-actuation state: `ENABLED` or `DISABLED`;
- connection status for ESP32;
- system state: `READY`, `BUSY`, `DEGRADED`, or `FAULT`;
- an unmistakable software control to disable automatic actuation where safe and available;
- guidance that the physical power disconnect/stop is independent of the dashboard.

Never present the API process's liveness alone as “System Ready.” Overall readiness is derived from the components needed for the selected operation.

### 5.3 Camera preview states

Required states:
- **Connecting:** explain that the camera is being opened.
- **Ready/live:** show selected camera and recent frame timestamp.
- **Stale:** visibly warn when frames are no longer updating.
- **Unavailable:** show a plain-language reason and recovery hint.
- **Capturing:** indicate a capture is in progress.
- **Processing:** freeze or retain the captured frame, mark it as the frame under inspection, and show progress.
- **Error:** state that no reliable decision was produced.

Do not keep showing a frozen frame as if it were live. Indicate frame age or last-updated time. A capture should have an identifiable frame hash/reference in the inspection record so the displayed evidence can be tied to the model result.

### 5.4 Inspection outcomes

Use persistent text labels:
- **PASS — Accepted by model policy:** required checks passed and score is within the qualified acceptance region. Do not describe it as a guarantee that the product is defect-free.
- **FAIL — Reject indicated:** qualified model evidence meets the rejection policy. Do not state that the item was physically rejected until action completion has been confirmed.
- **UNVERIFIED — Manual review required:** the evidence is missing, invalid, stale, inside the review band, or otherwise unsuitable for a reliable automatic decision.

For screen readers and non-color contexts, include the literal label and an appropriate icon/shape. Suggested colors may be green for PASS, red for FAIL, and amber for UNVERIFIED, but never rely on color alone. Display reason codes as operator-friendly text, with a detail view for technical codes.

### 5.5 Evidence panel

Show only values that the qualified model actually produces:
- model artifact/version and preprocessing version;
- score name, score value, and direction (e.g. higher means more anomalous);
- active policy version and thresholds when appropriate for the operator role;
- inference time;
- heatmap/overlay with a toggle to compare raw frame and overlay;
- warning when evidence cannot be displayed or was not produced.

Do not label an anomaly score as “probability” or “confidence percentage” unless the model is demonstrably calibrated and the meaning is documented. Heatmaps help interpretation but do not by themselves prove causality or defect location.

### 5.6 Action status panel

Keep quality outcome and physical action in separate sections.

| Action status | Operator meaning |
|---|---|
| `NOT_REQUESTED` | No physical action was asked for, e.g. PASS or review-only mode. |
| `PENDING` | A durable command intent exists but has not yet been sent. |
| `ACCEPTED` | Firmware accepted the command; movement is not yet confirmed. |
| `IN_PROGRESS` | Firmware reports the action has started, if supported. |
| `COMPLETED` | Firmware reported command completion; this may still not prove the item was diverted unless sensors verify it. |
| `FAILED` | A documented fault or failed action occurred. |
| `UNKNOWN` | The command may have reached the controller, but there is no definitive completion result. Do not blindly retry. |

The UI must never render `ACCEPTED` as “Item rejected.” For the current prototype, if no sensor confirms successful item diversion, show a note such as “Reject cycle reported complete; physical diversion not independently verified.”

### 5.7 Primary actions

Controls, subject to API support and interlocks:
- **Inspect now:** captures a new frame and starts an inspection.
- **Review result:** opens evidence and reason codes for the selected inspection.
- **Disable automatic actuation:** asks for confirmation if automatic operation is currently enabled and then requests a state change through the API.
- **Reconnect camera/controller:** a bounded diagnostic action, disabled while an incompatible operation is running.
- **Open review queue:** navigates to items requiring manual review.

Do not add an unguarded “force reject,” raw GPIO control, arbitrary serial console, or generic command execution to the normal operator interface. Advanced maintenance operations, if ever required, must be separately permissioned and bounded.

## 6. Inspection History

### 6.1 List view

Each row should show:
- timestamp (local display plus unambiguous ISO/UTC in details);
- inspection ID;
- camera/item/batch reference where available;
- outcome and reason summary;
- model and policy version;
- action status;
- overall record status.

Support filters for outcome, time range, camera, action status, and manual-review status. Pagination must be bounded, and the UI should preserve filters when opening and returning from a record.

### 6.2 Detail view

Show:
- captured frame and heatmap if retained;
- all capture metadata, including frame hash/reference and capture time;
- model output with score semantics and version;
- policy version, thresholds used, and decision rationale;
- action command ID, acknowledgement, completion/fault/unknown status, and event timestamps;
- manual resolutions and audit timeline;
- links to relevant system events.

Make initial model output immutable in the presentation. If a human resolves an item differently, show the human resolution as a separate event and do not overwrite the original decision.

## 7. Review Queue and manual resolution

Queue UNVERIFIED inspections and any cases explicitly flagged for review. Display age, reason, image/evidence availability, and current record version.

Review flow:
1. Operator opens an item and checks the captured frame and evidence.
2. Operator selects a permitted resolution, such as `ACCEPTED_BY_REVIEWER`, `REJECTED_BY_REVIEWER`, or `NEEDS_REINSPECTION`.
3. Operator enters a required reason and identity, if authentication is configured.
4. UI submits the resolution with the expected record version to avoid overwriting a concurrent update.
5. UI shows success only after the API confirms persistence.
6. Resolution appears in the audit timeline alongside the unchanged original model decision.

A manual review outcome must not silently trigger physical actuation. If a physical reject after manual review is supported later, make it a separate deliberate operation, verify current interlocks and item timing, and clearly disclose the consequence before submission.

## 8. System Status and fault handling

### 8.1 Component statuses

Represent at least:
- camera;
- model artifact loaded/qualified;
- inference service;
- database and disk capacity;
- serial connection;
- ESP32 heartbeat/firmware version where supported;
- motor/actuator readiness where sensed;
- automatic-actuation enable state;
- active command;
- recent faults and last successful event times.

A status should include the last update time. Unknown or stale telemetry must appear as `UNKNOWN`/`STALE`, not green/healthy.

### 8.2 Fault classes and operator messaging

| Fault | UI message pattern | Expected safe behavior |
|---|---|---|
| Camera disconnected | “Camera unavailable — reconnect or select a configured camera.” | No new PASS/FAIL decision; inspection remains unresolved/UNVERIFIED. |
| Model unavailable | “Inspection model is not ready.” | Do not accept items automatically. |
| Invalid/stale frame | “Frame could not be verified.” | Mark UNVERIFIED and retain reason. |
| Database write failure | “Result could not be saved; automation is paused.” | Do not issue a new actuator command when required durable state cannot be written. |
| ESP32 disconnected | “Controller disconnected — physical action unavailable.” | Show action as failed/unknown as appropriate; never claim physical rejection. |
| Command acknowledgement timeout | “Action status unknown — inspect the line before recovery.” | No blind automatic replay. |
| Actuator fault | “Reject mechanism reported a fault.” | Disable automatic actuation until reconciled. |
| Disk low/full | “Local storage is low/full.” | Warn early; pause safely if inspection evidence or audit logging can no longer be persisted. |
| Policy/model mismatch | “Inspection configuration is not qualified.” | Block automatic decisions and actuation. |

Display both a short operator explanation and a diagnostic code/detail. Recovery instructions should not encourage touching moving parts or bypassing guards/interlocks.

### 8.3 Stop and disable controls

The interface should provide a clearly visible software action to disable automatic actuation, if that feature is supported by the control plane. It is not a substitute for an accessible physical stop/power disconnect independent of software and firmware. Never label a software button “Emergency Stop” unless it is actually safety-rated and designed for that role; the prototype dashboard is not.

After a stop/fault:
- show why automatic actuation is disabled;
- require a deliberate reset/re-enable after the fault is reconciled;
- confirm current controller state and readiness before re-enabling;
- audit the reset and re-enable actions;
- leave unknown commands in an explicit reconciliation state.

## 9. Settings and permissions

Configuration should be grouped and labelled by risk:
- **Routine operator settings:** selected configured camera, history filters, display preferences.
- **Supervisor settings:** operating mode, auto-actuation enable/disable, approved policy selection if this is part of the implementation.
- **Maintenance/developer settings:** diagnostic export, connection settings, firmware/model metadata. No arbitrary GPIO/serial command console in production UI.
- **Qualification controls:** threshold changes, model replacement, preprocessing changes. These require a documented requalification process and immutable versioning; do not present threshold fields as casual tuning knobs.

If the dashboard is bound to LAN or accessed by multiple people, implement authentication and role permissions at the API layer. Hiding a button in the frontend is not authorization. Record all privileged actions in the audit log.

## 10. Visual system and accessibility

### 10.1 Recommended visual direction

Use a clean industrial operator-console style:
- dark charcoal or neutral off-white base with high-contrast text;
- restrained red for fault/reject indicators and neutral status treatment elsewhere;
- large outcome typography and clear spacing;
- crisp borders and simple panels instead of glassmorphism, gradients, or decorative effects;
- monospace only for IDs, scores, versions, and diagnostic codes;
- subtle motion only for progress and live updates, with reduced-motion support.

The exact colors must meet contrast standards in the implemented theme. Do not use color alone for status or inline error messaging.

### 10.2 Accessibility requirements

- All functions usable with keyboard.
- Visible focus indicators and logical tab order.
- Form controls have persistent labels, and errors are connected to inputs.
- Status updates are announced politely to assistive technology; do not announce every video frame.
- Outcome text and action state are not conveyed by color alone.
- Text can scale to 200% without hiding critical controls.
- Interactive targets are comfortably sized.
- Motion respects the operating-system reduced-motion preference.
- Charts and heatmaps have textual summaries or an accessible alternative.
- Timestamp and score formatting are consistent and locale-aware.

## 11. Frontend state model

Use explicit UI state rather than inferring from whether a value happens to be present. Suggested state groups:

- `cameraState`: `CONNECTING | LIVE | STALE | UNAVAILABLE | ERROR`
- `inspectionState`: `IDLE | CAPTURING | PROCESSING | DECIDED | ERROR`
- `decisionOutcome`: `PASS | FAIL | UNVERIFIED | NONE`
- `actionState`: `NOT_REQUESTED | PENDING | ACCEPTED | IN_PROGRESS | COMPLETED | FAILED | UNKNOWN`
- `systemState`: `READY | BUSY | DEGRADED | FAULT | UNKNOWN`
- `operatingMode`: `AUTOMATIC | REVIEW_ONLY`
- `autoActuationEnabled`: boolean plus last-confirmed timestamp
- `reviewState`: `NOT_REQUIRED | REQUIRED | IN_PROGRESS | RESOLVED`

Rules:
- Show loading/progress during transitions.
- Ignore or visibly reject stale/out-of-order events; associate updates with request and inspection IDs.
- Refresh/reconcile server state after network/serial reconnect rather than assuming the last local UI state is authoritative.
- Treat missing or stale backend data as unknown.
- Display success only after server confirmation.
- Avoid optimistic UI for physical action completion or manual-resolution persistence.

## 12. API integration

Use the contract proposed in Document 07, subject to verification against the actual implementation:
- `GET /api/v1/health`
- `GET /api/v1/readiness`
- `POST /api/v1/inspections`
- `GET /api/v1/inspections/{inspection_id}`
- `GET /api/v1/inspections`
- `POST /api/v1/inspections/{inspection_id}/manual-resolution`
- `GET /api/v1/metrics` (restricted)

Frontend requirements:
- centralize API client and error mapping;
- configure timeouts and cancellation for requests that can safely be cancelled;
- do not automatically retry a non-idempotent inspection POST unless the same idempotency key is reused;
- preserve the inspection ID so the client can recover after refresh;
- poll or subscribe only through a documented server mechanism;
- avoid high-frequency polling that overloads the laptop;
- gracefully handle backend restart and loss of connection;
- never send model thresholds or a client-computed decision as authority for automatic actuation.

Use the backend's stable error codes to produce safe, helpful messaging. A technical details panel can show the request ID and error code without exposing stack traces.

## 13. Data freshness, latency, and rendering

- Show the capture timestamp and most recent camera frame timestamp.
- Use a configurable stale-frame threshold determined during testing.
- Separate camera preview refresh from inspection requests.
- Avoid blocking the whole UI while inference runs.
- Display inference duration only after a valid server measurement is returned.
- Provide a clear in-progress state for long operations.
- Bound image sizes and use thumbnails for history lists.
- Revoke obsolete object URLs/release image resources where browser APIs and framework patterns require it.
- Ensure a heatmap always refers to the same frame and inspection ID as the displayed result.

Do not set arbitrary production latency targets here before benchmarking the actual laptop, model, camera, and object category. Establish and document p50/p95 timings during qualification and use a measured budget for the first release.

## 14. Privacy and retention

- Keep frame storage local by default.
- Do not upload images or diagnostics to a third party without an explicit user-configured feature and appropriate notice.
- Show when images are stored and how long they are retained.
- Limit access to raw frames, heatmaps, and diagnostic exports if the service is network-accessible.
- Avoid collecting personal data; product/batch identifiers should be operationally necessary and retention-limited.
- Ensure logs do not contain credentials, secrets, or full raw images.
- Provide a safe diagnostic bundle with secrets and sensitive data redacted.

## 15. Frontend testing plan

### Component tests
- all outcome labels and reason codes;
- camera live/stale/unavailable views;
- action status distinctions, especially ACCEPTED versus COMPLETED versus UNKNOWN;
- review form validation and conflict response;
- keyboard focus and accessible names;
- loading, empty, and backend error states.

### Integration tests
- successful inspection lifecycle;
- inference timeout or malformed result;
- duplicate submission with reused idempotency key;
- refresh during processing and recovery of inspection status;
- ESP32 disconnect after FAIL decision;
- action timeout reported as UNKNOWN;
- database persistence failure;
- manual-review permission denied and optimistic-concurrency conflict;
- filters, pagination, and navigation preserving context.

### End-to-end / hardware-in-loop
- camera preview, inspection, outcome, and history in one flow;
- FAIL with controller disconnected does not show “rejected”;
- PASS produces no reject command;
- UNVERIFIED enters review queue and does not actuate automatically;
- software auto-actuation disable prevents new automatic commands;
- physical stop/power disconnect remains independent of UI behavior;
- reload/reconnect recovers state from the server rather than local assumptions.

### Acceptance criteria
- Primary live workflow fits on the intended laptop display without hiding current decision or fault state.
- PASS, FAIL, UNVERIFIED, and action status remain distinguishable without color.
- A frozen frame is never presented as live.
- The dashboard never treats model score as a probability unless proven calibrated.
- A model FAIL is never presented as proof that an item was physically rejected.
- UNKNOWN action state triggers reconciliation messaging and is not automatically replayed.
- Manual resolution includes a reason and produces an immutable audit event.
- The interface remains useful offline with the local API and model running.
- Critical controls are keyboard accessible and have visible focus.
- Errors are actionable for operators and detailed enough for maintainers without leaking secrets.

## 16. Suggested implementation order

1. Audit existing frontend framework, routes, styling, API client, and available assets.
2. Implement shared typed API schemas and error-state components.
3. Build the Live Inspection layout using mocked but realistic states.
4. Integrate real health/readiness endpoints and component freshness.
5. Integrate inspection submission/resource polling with idempotency.
6. Add distinct outcome, evidence, and physical-action panels.
7. Add history, detail timeline, and review queue.
8. Add role-aware manual resolution and guarded settings.
9. Add responsive layout and accessibility checks.
10. Complete integration and hardware-in-loop acceptance tests before enabling automatic actuation.

## 17. Open questions to verify

- What frontend framework, router, component library, and CSS system already exist?
- What screen resolution is available on the actual laptop during the demo?
- Which camera preview integration will be used by the repository?
- Does the backend deliver heatmaps as files, URLs, or encoded data?
- Which ESP32 telemetry states are actually implemented and trustworthy?
- Is this single-operator/localhost-only, or will LAN/multiple-user access be supported?
- What image and audit retention duration is required?

Answer these from the real repository and prototype before treating this specification as implemented behavior.
