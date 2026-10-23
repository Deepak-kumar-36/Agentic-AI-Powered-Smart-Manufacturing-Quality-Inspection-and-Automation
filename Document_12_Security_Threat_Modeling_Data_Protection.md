# Document 12 — Security, Threat Modeling & Data Protection

**Project:** Agentic AI Smart Manufacturing Quality Inspection & Automation Platform  
**Document type:** Security engineering specification and operating procedure  
**Version:** 1.0  
**Status:** Proposed design; implementation must be verified against the actual repository  
**Target deployment:** Local-first tabletop prototype using a phone camera, Linux/Arch workstation, local anomaly-detection inference, local storage, web dashboard, and ESP32-class microcontroller.

---

## 1. Executive Summary

This document defines minimum security and data-protection controls for the prototype. The initial system is expected to run locally, with a phone used as a camera, a Linux workstation acting as the decision authority, and an ESP32 executing a small, bounded set of hardware commands.

The main security objective is to protect inspection integrity and physical predictability. An attacker or software fault must not be able to turn missing evidence into `PASS`, silently change decision thresholds, issue arbitrary motor/servo instructions, erase audit history without detection, or expose inspection artifacts by default.

This is a **proposed specification**. The actual repository, dependency list, API configuration, firmware, and runtime deployment have not been inspected in this document. Treat every implementation status as unverified until tested.

## 2. Security Goals and Non-Goals

### 2.1 Security goals
- Preserve integrity of inspection images, model outputs, decisions, policy versions, and audit records.
- Limit who and what can request inspections, change configuration, review data, or request bounded machine actions.
- Prevent arbitrary commands from reaching motors or servos.
- Keep local inspection operational without cloud connectivity.
- Minimize exposure of camera imagery, credentials, model artifacts, and operator information.
- Make unexpected software, model, firmware, or configuration changes detectable.
- Support safe restart, recovery, and investigation after faults.

### 2.2 Non-goals and explicit limitations
- The prototype is not a certified industrial controller, functional-safety system, or safety-rated PLC.
- These controls do not establish compliance with a specific law, standard, certification, or industry framework.
- A local network is not automatically trusted; “local-only” reduces exposure but is not a substitute for access control.
- A hash alone does not prove an image is true, correctly labeled, or captured from the claimed physical item.
- An anomaly score is not proof of malicious activity or product defect.
- The LLM or agent layer is never authorized to bypass deterministic decision policy or send arbitrary hardware instructions.

## 3. System and Trust Boundaries

### 3.1 Components
1. **Phone camera / capture adapter:** produces frames. May connect through USB webcam mode or a local Wi-Fi camera application.
2. **Local web dashboard:** displays status, inspection outcome, evidence, and review controls.
3. **API / orchestration service:** validates requests, sequences capture and inference, persists records, and orchestrates approved actions.
4. **Model runtime:** performs inference and returns outputs with defined semantics.
5. **Decision policy:** deterministic, versioned rules producing `PASS`, `FAIL`, or `UNVERIFIED`.
6. **Local database and artifact storage:** stores records, hashes, events, images, and heatmaps.
7. **ESP32 firmware:** accepts a bounded protocol, reports state, and executes permitted actions.
8. **Operator / developer workstation:** interactive access, software updates, logs, and configuration.
9. **Optional future sync or remote access:** disabled by default and separately reviewed before enabling.

### 3.2 Trust boundaries
- Browser ↔ local API.
- API ↔ model runtime.
- API ↔ database and filesystem.
- API ↔ USB/serial ESP32 device.
- Phone/camera app ↔ workstation capture path.
- Operator account ↔ privileged configuration and release artifacts.
- Optional sync boundary ↔ external system.

A trust boundary must have explicit validation and failure behavior. Do not rely on the fact that components are on one device or one Wi-Fi network.

## 4. Assets to Protect

| Asset | Integrity need | Confidentiality need | Availability need |
|---|---|---|---|
| Inspection result and reason code | Critical | Medium | High |
| Original image / heatmap | High | Potentially high | Medium-high |
| Model weights and release manifest | Critical | Medium | High |
| Decision thresholds and policy version | Critical | Medium | High |
| ESP32 commands and machine state | Critical | Low-medium | High |
| Inspection database and audit events | Critical | High | High |
| API credentials and signing keys, if used | Critical | Critical | Medium |
| Camera and network configuration | High | Medium | High |
| Software dependencies and firmware | Critical | Medium | High |
| Backups and export files | Critical | High | Medium-high |

Security prioritization should focus first on decision integrity, bounded actuation, audit durability, and the protection of captured imagery.

## 5. Threat Model

Use the following working attacker/failure profiles during design and testing:
- A malicious or compromised browser on the same local network.
- A user who can access the workstation but should not be able to alter policy or release artifacts.
- An accidental operator action or misconfigured service.
- A malicious, malformed, stale, or corrupted API request.
- A process that crashes between persisting a decision and issuing/acknowledging an actuator command.
- A rogue or unintended serial device, or noisy/partial serial data.
- A compromised dependency, poisoned artifact, or accidental software update.
- A lost or stolen workstation/phone or copied backup.
- A network adversary if future Wi-Fi access or remote sync is introduced.
- An AI/agent component that proposes an unsafe action, hallucinated command, or unauthorized policy change.

### 5.1 Threat register

| ID | Threat | Potential impact | Required control | Verification |
|---|---|---|---|---|
| T-01 | Unauthorized API request | False inspections, unwanted action requests, data disclosure | Bind to loopback by default; enforce authentication/authorization if network reachable; validate origin/CSRF where browser sessions are used | From another host, requests are blocked unless explicitly authorized |
| T-02 | Malformed or oversized image upload | Resource exhaustion, parser faults, corrupt evidence | Byte-size limits, allowed formats, content decoding validation, pixel-dimension caps, timeouts | Oversized, truncated, mislabeled, and decompression-heavy files rejected |
| T-03 | Decision threshold changed without approval | Silent quality regression or false acceptance | Versioned configuration, restricted write path, audit event, release gate | Attempts by viewer/operator/agent role are denied |
| T-04 | Arbitrary serial command or PWM value | Unexpected motor/servo movement | Typed allow-listed commands; firmware-side limits; no arbitrary GPIO/write shell access | Unknown opcode and out-of-range values rejected |
| T-05 | Duplicate command after timeout/retry | Repeated reject motion or inconsistent item state | Idempotency key; persistent command state; duplicate suppression; reconcile before retry | Replaying identical command does not repeat a completed action |
| T-06 | Stale result applied to a new item | Incorrect physical disposition | Bind result to inspection ID, frame hash, sensor/item cycle, and freshness deadline | Old result cannot authorize a later item |
| T-07 | Model artifact replaced or corrupted | Untrustworthy inference | Immutable release ID, hash verification, controlled artifact directory, readiness check | Modified artifact fails verification and system does not mark ready |
| T-08 | Database/artifacts modified or deleted | Lost traceability or forged audit | Least privilege, append-only event pattern, backups, file permissions, integrity checks | Unauthorized write fails; restore drill succeeds |
| T-09 | Secrets committed or logged | Unauthorized access | Environment/secret files outside repo, restrictive permissions, redaction, rotation | Secret scanning and log review find no active secrets |
| T-10 | Dependency or firmware supply-chain compromise | Code execution or hidden behavior | Pinned dependencies, lockfiles, provenance, reviewed upgrades, firmware release hash | Reproducible install and upgrade review evidence retained |
| T-11 | Camera captures unrelated people/background | Privacy exposure | Fixed framing, minimal capture, access controls, retention policy, avoid audio by default | Test frames contain only required inspection area |
| T-12 | Prompt injection / unsafe agent proposal | Unauthorized policy or hardware change | Treat all agent output as untrusted proposal; deterministic allow-list and human approval | Adversarial output cannot change decisions or issue arbitrary actuator commands |
| T-13 | Service binds to all interfaces accidentally | Unexpected network exposure | Explicit host binding, startup assertion, firewall where appropriate | Socket/listening-address test confirms intended exposure |
| T-14 | Disk full or power loss | Missing evidence, partial transaction | Atomic persistence, disk monitoring, write failure mapped to `UNVERIFIED`, recovery tests | Injected storage failure never returns an unpersisted result as completed |
| T-15 | Serial device spoofing / wrong device selected | Commands sent to unexpected hardware | Explicit device selection, VID/PID or stable path where practical, startup handshake and firmware identity | Wrong/unrecognized device cannot be enabled |
| T-16 | Backup/export leaks imagery or configuration | Privacy or security breach | Controlled export, encryption where needed, scoped access, retention and deletion process | Export permissions and restore workflow tested |

## 6. Security Architecture Requirements

### 6.1 Local API exposure
- Default to loopback binding, such as `127.0.0.1`, for a single-workstation prototype.
- If the dashboard must be opened from another device, define that deployment explicitly: dedicated trusted Wi-Fi, authentication, authorization, request limits, and firewall rules.
- Do not use `0.0.0.0` by default or expose the service to the internet.
- Never assume CORS alone is an authentication mechanism.
- If cookie-based sessions are used, implement CSRF protection and secure cookie settings appropriate to the transport.
- If bearer tokens are used, keep them out of URLs and logs, and require rotation/revocation procedures.
- Provide distinct readiness and liveness checks; do not expose secrets, full paths, or detailed internals in public health responses.

### 6.2 Authentication and authorization
For the local prototype, keep privileged controls minimal and explicit. If more than one operator or any network access is possible, implement at least these conceptual roles:
- **Viewer:** may view status and allowed inspection history.
- **Operator:** may start inspection and perform approved manual review actions.
- **Maintainer:** may manage configuration, model release selection, and diagnostics.
- **Administrator:** may manage identities and security-sensitive settings.

Enforce authorization in the backend, not only by hiding buttons in the UI. Apply deny-by-default rules to unrecognized roles. Do not reuse developer/admin privileges for the normal demo operator account.

### 6.3 Configuration and secrets
- Never commit `.env`, API credentials, private keys, Wi-Fi credentials, or access tokens.
- Use a local secrets file only where necessary, owned by the service user and permission-restricted (for example `chmod 600`).
- Provide a `.env.example` containing placeholder values only.
- Redact secret values from logs, exceptions, screenshots, issue reports, and exported diagnostics.
- Rotate any credential that has been committed or shared; removing it from the latest commit is not sufficient if it may remain in history.
- Avoid storing credentials in browser local storage unless there is a reviewed reason and mitigation.

### 6.4 Input validation and resource limits
- Validate JSON structure, types, enum values, string lengths, numeric ranges, and required fields.
- Set request-body, upload-size, pixel-dimension, concurrency, and processing time limits.
- Validate image content by decoding it; do not trust only the extension or MIME header.
- Reject path traversal, arbitrary filesystem paths, shell fragments, unexpected Unicode/control characters where relevant, and unknown protocol fields when strict schemas are required.
- Use parameterized SQL and migration-controlled schemas.
- Do not accept client-supplied model file paths, arbitrary threshold expressions, executable Python, shell commands, or arbitrary GPIO values.
- Return typed, non-sensitive errors; log detailed diagnostic context locally with redaction.

### 6.5 Filesystem and database
- Run the service as an unprivileged user; do not run the API or model service as root.
- Give each process only the files/devices it needs.
- Store data in a clearly defined application directory, not arbitrary user-supplied paths.
- Separate mutable configuration from immutable model-release artifacts.
- Use atomic file creation for artifacts and ensure database transactions complete before marking an inspection as durably finished.
- Keep image bytes outside relational tables where practical; store hashes and references in the database.
- Restrict database and artifact permissions; make routine exports explicit.
- Test backup, restore, disk-full, file-permission, and partial-write scenarios.

## 7. ESP32 and Physical-Action Security

### 7.1 Command allow-list
The workstation must issue only typed, documented commands such as:
- `STATUS_REQUEST`
- `SET_INDICATORS` using a fixed enum
- `BELT_START` or `BELT_STOP` within a defined state machine
- `REJECT_ONCE` with an inspection/command ID
- `ACK` / status query messages as defined in the firmware protocol

The final command names must match the actual firmware specification and implementation. This list is conceptual, not a claim that these exact opcodes already exist.

### 7.2 Never expose arbitrary low-level control
The API must not provide endpoints such as:
- arbitrary GPIO write,
- raw PWM duty cycle,
- arbitrary servo angle,
- arbitrary serial pass-through from a browser,
- shell command execution,
- free-form “agent instruction” sent to firmware.

If actuator calibration is needed, use a maintainer-only offline procedure with hard-coded safe bounds and the drive system disabled where possible.

### 7.3 Firmware-side controls
Firmware must independently validate:
- supported protocol version,
- message framing and maximum length,
- JSON or binary schema,
- command allow-list,
- numeric limits and enum values,
- duplicate command IDs,
- state prerequisites,
- watchdog/timeout behavior,
- motor/servo action duration,
- invalid or partial message behavior.

The ESP32 is not assumed to be a certified safety controller. Firmware limits reduce risk but do not replace physical power isolation, supervision, guarding, or a proper safety system in industrial deployment.

### 7.4 Decision/action separation
- The laptop remains the decision authority.
- Persist the inspection decision and a unique machine-command record before dispatch.
- A model `FAIL` is not proof that a reject action completed.
- Require command acknowledgment and a separate completion event/status.
- After a lost acknowledgment, reconcile current firmware/physical state before retrying.
- A duplicate retry must not cause a second reject cycle for the same inspection.
- Stale results must never be applied to a later item.
- `UNVERIFIED` uses the defined hold/manual path; it must not auto-accept by default.

## 8. Model, Agent, and Policy Security

- Pin and record model/runtime/preprocessing versions for each qualified release.
- Verify hashes of model artifacts before loading; reject unexpected artifact paths.
- Do not load model files from untrusted sources.
- Isolate model loading/inference where practical; enforce timeouts and memory/resource limits.
- Treat heatmaps, scores, file names, camera metadata, and operator-entered strings as data, not instructions.
- An LLM/agent may summarize logs or propose a review task, but it must not modify thresholds, release selection, labels, or hardware state without a deterministic authorization gate.
- Keep inference output separate from policy output; validate schema, numeric finiteness, ranges, and model readiness.
- Reject NaN, infinity, missing scores, stale results, incompatible release metadata, and unexpected tensor/image dimensions.
- Do not feed untrusted image metadata or operator notes into shell commands or dynamic code.
- Keep training/evaluation sets isolated and track data provenance and licenses.
- A model update is a release event requiring evaluation, approval, recorded rollback target, and post-release monitoring.

## 9. Privacy and Data Protection

### 9.1 Camera minimization
- Frame only the target inspection region; avoid faces, screens, paperwork, and unrelated surroundings.
- Do not capture audio unless there is a separately approved need.
- Store only what is required for inspection, evaluation, troubleshooting, and audit.
- Document whether frames are retained, for how long, and who can access or export them.
- Use synthetic or redacted images for issue reports where possible.

### 9.2 Retention and deletion
Define a written retention schedule for:
- original inspection images,
- anomaly heatmaps and derived artifacts,
- routine telemetry,
- security/audit events,
- crash logs and diagnostic exports,
- backups.

Deletion must not remove the only evidence for an open incident or break referential integrity without an auditable process. The retention periods are an open project decision; do not invent a universal period here.

### 9.3 Access and exports
- Limit access to authorized operators/maintainers.
- Keep exported images and logs in controlled locations.
- Use encrypted storage or encrypted archives when the threat model includes device theft or transport of exports.
- Review exports for secret values and unrelated camera content.
- Do not transmit imagery to cloud services by default. Any future sync must have an explicit purpose, access policy, retention rule, and offline behavior.

## 10. Dependency and Software Supply-Chain Controls

- Maintain pinned dependencies and a lockfile for each supported runtime environment.
- Separate application dependencies, model dependencies, and firmware toolchain versions.
- Review upgrades before installation; avoid unreviewed remote install scripts in production-like runs.
- Record Python/Node package versions, OS version, firmware build identifier, and model runtime.
- Run dependency and secret scans when practical and review findings before release.
- Build artifacts from known source; record hashes for release bundles and firmware binaries.
- Keep generated datasets and model weights clearly distinguished from source code.
- Restrict write access to release folders; do not overwrite known-good artifacts in place.
- Update one layer at a time and rerun the integration test plan after changes.
- Back up configuration and a known-good release before major upgrades.

## 11. Logging, Monitoring, and Audit

Record security-relevant events such as:
- authentication/authorization failures,
- configuration and threshold changes,
- model/firmware release changes,
- rejected malformed requests,
- API bind/configuration changes,
- device selection and firmware identity,
- command issue, ACK, completion, timeout, and reconciliation,
- image validation failures,
- database and artifact write failures,
- review overrides and data exports,
- backup/restore actions.

Each event should include a timestamp, event type, correlation/inspection/command ID where relevant, actor or service identity, result, and a redacted diagnostic reason.

Never log passwords, bearer tokens, private keys, full secret-bearing environment dumps, or unnecessary image bytes. Use structured logs; restrict access to logs; monitor disk use; document clock/time-zone behavior. For local-only operation, logging must not depend on cloud access.

## 12. Secure Startup and Recovery

### Startup checks
1. Verify required configuration exists and contains no unresolved placeholders.
2. Assert the intended network bind address.
3. Verify model manifest and artifact hash.
4. Check database access, schema version, and disk space.
5. Identify the expected serial device and verify firmware/protocol identity.
6. Keep actuator execution disabled until the operator explicitly arms the supervised tabletop prototype.
7. Run health/readiness checks and display model/policy version.

### Failure behavior
- Invalid input, model unavailability, stale data, failed persistence, or incompatible versions must not produce `PASS`.
- If decision persistence fails, do not claim a completed durable inspection.
- If physical action state is ambiguous, hold the sequence and reconcile before resuming.
- Do not replay non-idempotent actions blindly after a crash.
- Restarting services must not silently change model/policy version or reset audit state.
- When disk space is critically low, stop accepting new inspections cleanly or fail them as `UNVERIFIED`; do not silently discard records to continue.

## 13. Verification Checklist and Security Tests

| Test ID | Test | Expected outcome |
|---|---|---|
| SEC-01 | Start service with default configuration | Binds only to the declared local address; no unintended listener |
| SEC-02 | Send request from a second host | Blocked unless explicit network mode and authorization are configured |
| SEC-03 | Send unknown enum, malformed JSON, extreme numbers, and oversized payload | Rejected with typed error; no state change |
| SEC-04 | Upload truncated, mislabeled, high-dimension, or unsupported image | Rejected or marked `UNVERIFIED`; no `PASS` |
| SEC-05 | Attempt threshold/model change as viewer/operator | Denied and audit event created |
| SEC-06 | Attempt arbitrary GPIO/PWM/servo parameter or serial pass-through | No API path exists or request is rejected |
| SEC-07 | Replay a completed reject command with same idempotency key | Does not repeat physical action |
| SEC-08 | Replay a result for a previous inspection | Rejected as stale/mismatched |
| SEC-09 | Modify a model artifact after manifest creation | Hash verification fails and readiness is false |
| SEC-10 | Force DB write failure or disk-full condition | Inspection not falsely reported as durably complete; outcome fails closed |
| SEC-11 | Search application and repo history/logs for test secrets | No active secrets exposed; any exposure triggers rotation |
| SEC-12 | Stop/restart the API between decision and command completion | Recovery reconciles state; no blind duplicate action |
| SEC-13 | Connect an unknown serial device | Device is not armed; identity/protocol check fails |
| SEC-14 | Provide hostile LLM output suggesting threshold or GPIO change | Agent cannot apply it; deterministic authorization rejects it |
| SEC-15 | Export diagnostics | Secrets are redacted and only approved artifacts included |
| SEC-16 | Restore a backup on a clean environment | Records, manifests, and artifact references verify consistently |
| SEC-17 | Check logs during failures | Useful audit trail exists without secrets or excessive image data |
| SEC-18 | Run without network/cloud | Core inspection, local persistence, and operator display still work |

## 14. Incident Response Procedure

For a suspected compromise, unexpected actuator movement, unauthorized policy change, artifact mismatch, or evidence tampering:

1. **Hold safely:** stop the tabletop sequence and isolate motor power if behavior is uncertain. Do not rely only on a UI stop button.
2. **Preserve evidence:** retain relevant logs, inspection IDs, command IDs, hashes, version manifests, and timestamps.
3. **Limit exposure:** disconnect unnecessary network access; do not delete suspicious artifacts or logs.
4. **Identify scope:** determine which inspections, releases, commands, data exports, and credentials may be affected.
5. **Recover deliberately:** restore a known-good release or backup only after integrity checks.
6. **Rotate credentials:** revoke exposed tokens/keys and remove inappropriate access.
7. **Verify:** rerun the security and integration checks before re-enabling supervised operation.
8. **Document:** record root cause, affected period, corrective actions, owner, and approval to resume.

For any uncertainty about physical state, prioritize isolation and supervised reconciliation over attempting to keep the demo running.

## 15. Implementation Roadmap

### Phase A — Exposure reduction
- Confirm API binds to loopback by default.
- Run service as unprivileged user.
- Create example-only environment template and secret-handling rules.
- Define filesystem and database permissions.
- Disable unused remote-sync and debug endpoints.

### Phase B — Command and decision integrity
- Add strict request and serial-message schemas.
- Add model/policy release IDs and hash checks.
- Ensure `UNVERIFIED` behavior on invalid input/model/persistence failure.
- Add idempotent machine command state and stale-result protection.
- Remove any route capable of arbitrary GPIO, shell, or serial pass-through.

### Phase C — Audit and recovery
- Add structured security events and redaction.
- Test database/artifact backup and restore.
- Exercise crash windows and serial disconnects.
- Add startup checks and explicit supervised arming.

### Phase D — Hardening review
- Review dependencies, permissions, network listeners, exports, and retention.
- Run the security test checklist.
- Resolve all critical findings before a public or shared-network demonstration.
- Reassess threat model before enabling Wi-Fi access, cloud sync, or remote control.

## 16. Release Gate

Do not mark a release security-ready until:
- [ ] No unintended network listener is exposed.
- [ ] Authentication and backend authorization match the deployment mode.
- [ ] Model and policy versions are immutable and auditable.
- [ ] The serial protocol is bounded and rejects unknown commands.
- [ ] Duplicate and stale machine actions are safely handled.
- [ ] Secrets are excluded from source and logs.
- [ ] Invalid input and system faults fail closed to `UNVERIFIED`/hold behavior.
- [ ] Database/artifact recovery tests pass.
- [ ] Retention and export handling are documented.
- [ ] Security tests are recorded, findings triaged, and approval captured.

## 17. Open Decisions

Resolve these based on the actual implementation and deployment plan:
- Exact API framework, listening address, and any authentication mechanism.
- Browser hosting topology and whether more than one device needs access.
- Current USB/serial protocol, firmware identity handshake, and command semantics.
- Data directory, encryption requirement, backup destination, and retention schedule.
- Operator roles and approval permissions.
- Dependency lockfile, firmware build process, and artifact-signing approach.
- Whether future deployment requires a formal compliance, privacy, or functional-safety assessment.

## 18. Final Security Rule

The platform must prefer **known-safe hold and transparent failure** over a convenient but unverified result. No model, agent, API request, dashboard control, retry mechanism, or firmware message may bypass deterministic policy, immutable traceability, or bounded physical actions.

## Experimental Gemini vision assessment data handling

The optional Gemini advisory path is disabled by default and sends no image
unless an operator explicitly requests an assessment for a selected inspection.
The backend accepts only an inspection ID, resolves a relative image reference
inside configured managed evidence roots, validates its bytes and stored SHA-256,
and sends only that image to Google. It does not accept client filesystem paths
or transmit inspection databases, API credentials, or unrelated record metadata.
The server-side key is never returned to the dashboard or written to logs.
Images sent to Google are subject to applicable provider terms, privacy policy,
retention practices, and usage charges. The provider call has a bounded timeout
and per-inspection request throttle. Its `DEMO_ADVISORY` output is unqualified
and has no path to decision persistence, training labels, or hardware commands.
