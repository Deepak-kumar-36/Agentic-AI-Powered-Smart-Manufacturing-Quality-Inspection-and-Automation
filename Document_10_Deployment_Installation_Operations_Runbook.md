# Document 10 — Deployment, Installation & Operations Runbook

**Project:** Agentic AI Smart Manufacturing Quality Inspection & Automation Platform  
**Version:** 1.0 (proposed deployment runbook)  
**Target:** supervised tabletop prototype on Arch Linux; phone used as camera; laptop/PC runs local inference; ESP32 controls low-voltage peripherals.  
**Status:** implementation-neutral operational guide. Commands containing example paths, module names, or scripts must be aligned to the actual repository before being treated as executable.

> **Important boundary:** This runbook is for a supervised, low-voltage tabletop prototype only. It is not a certified industrial safety system and must not be connected to a production PLC, production conveyor, or safety circuit. Keep a reachable physical power disconnect. The physical machine must fail to a stopped/held state when the decision service, serial link, or controller is unhealthy.

## 1. Purpose and operating principles

This runbook explains how to prepare a Linux workstation, install the application dependencies, connect and verify the camera and ESP32, start the local stack, operate inspections, recover from faults, and prepare a repeatable demonstration.

Core operating rules:

- **Local-first:** inspection and decision-making continue without cloud access. Network access is not required for the core inspection path.
- **Fail closed:** invalid frames, unavailable model, stale results, API/storage failures, or uncertain machine state must never become `PASS` by default. Resolve as `UNVERIFIED` or stop/hold the machine.
- **Separate decision from actuation:** `PASS`/`FAIL`/`UNVERIFIED` is the inspection outcome; command acknowledgement and physical action completion are separate states.
- **Bounded controller commands:** the application can send only allowlisted commands such as STOP/HOLD, RESUME, and one bounded reject-cycle request. No LLM or agent can send arbitrary GPIO, PWM, shell, or servo-angle commands.
- **Traceability:** retain inspection ID, timestamps, image hash/artifact reference, model and policy versions, decision reason, controller command ID, acknowledgements, and operator review.
- **Human-supervised prototype:** do not run unattended. Keep hands clear of the belt, rollers, motor coupling, and reject arm.

## 2. Deployment model and assumptions

### 2.1 Logical services

| Component | Responsibility | Startup requirement |
|---|---|---|
| Camera adapter | Opens the selected phone/webcam stream and supplies a frame | Camera device is present and selected explicitly |
| Inspection API/orchestrator | Validates request, coordinates capture/inference/persistence and bounded controller action | Local config loaded; storage writable |
| Model runtime | Loads the qualified PatchCore model and emits score/heatmap/artifact references | Model artifact and its metadata match the active release |
| Decision policy | Maps validated inference and image-quality checks to PASS/FAIL/UNVERIFIED | Versioned policy and approved thresholds present |
| Local persistence | Stores inspection records, event audit, command state and artifact references | DB path and artifact directory writable |
| ESP32 link | Sends allowlisted commands and receives ACK/status events | Serial port stable; firmware version recorded |
| Operator dashboard | Displays live state, results, review workflow and system health | API URL correct; API health check passes |

This is the target deployment decomposition, not proof that each service already exists in the codebase. Document 03 found that an identifiable source repository was not available for inspection. Confirm the actual module paths, package manager, service boundaries, and command names before using the example commands below.

### 2.2 Suggested local topology

- Browser dashboard → API bound to `127.0.0.1` by default.
- API/orchestrator → local model runtime and local DB/files.
- API/orchestrator → ESP32 over USB serial (preferred for first prototype).
- Phone → laptop camera input by supported USB webcam mode or local Wi-Fi stream on a trusted private network.
- No inbound internet exposure; do not port-forward the dashboard/API.

### 2.3 Required release/configuration inventory

Before first install, identify and record:

- Repository URL or local path and exact Git commit.
- Python and Node versions actually supported by lockfiles/configuration.
- Python lock/dependency file and frontend package manager/lockfile.
- Model artifact path, cryptographic hash, model version, expected image dimensions/normalization, and dataset/evaluation report.
- Decision policy version and formally selected thresholds/review band. Do not invent thresholds during deployment.
- Camera source/index or stream endpoint, camera resolution/frame rate, fixed mount position, and lighting profile.
- ESP32 board, firmware version/hash, selected serial port, GPIO/driver mapping, and controller protocol version.
- DB and artifact paths, free disk space, backup destination, and log location.

## 3. Workstation prerequisites

### 3.1 Base system checks (Arch Linux)

Run as the normal user unless a command explicitly requires administrator privileges.

```bash
uname -a
python --version || true
python3 --version
node --version || true
npm --version || true
git --version
lsblk -f
df -h "$HOME"
```

Install only the tools needed by the repository and selected capture path. Example base packages:

```bash
sudo pacman -Syu
sudo pacman -S --needed git python python-pip v4l-utils ffmpeg usbutils
```

Install Node.js only if the dashboard is a Node-based frontend. Prefer the version specified by `.nvmrc`, `package.json` `engines`, or equivalent repository metadata; do not upgrade runtimes casually on demo day. If a Python package requires compilation, install only the documented compiler/build dependencies. Keep a note of every system package added.

### 3.2 Verify repository identity and cleanliness

```bash
cd /path/to/repository
pwd
git status --short
git rev-parse --show-toplevel
git rev-parse HEAD
find . -maxdepth 2 -type f \( -name 'pyproject.toml' -o -name 'requirements*.txt' -o -name 'uv.lock' -o -name 'package.json' -o -name 'pnpm-lock.yaml' -o -name 'package-lock.json' -o -name 'poetry.lock' \) -print
```

Replace `/path/to/repository` with the real path. If no repository or dependency lockfile is available, stop and establish the code source and supported install procedure before continuing. Do not manufacture a requirements file from guesses.

### 3.3 Python environment

Use the dependency strategy present in the repository. Example only for a project with a compatible `requirements.txt`:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip check
```

If the repository uses `uv`, Poetry, Conda, or another lockfile-based tool, follow its locked installation instead. Never install into system Python with `sudo pip`. Store model artifacts outside source control if they are large or licensed separately, and verify their hash before startup.

### 3.4 Frontend environment (only if applicable)

Use the exact package manager indicated by the lockfile; do not mix npm/pnpm/yarn in the same install.

```bash
node --version
corepack --version || true
# Example only for a pnpm lockfile:
corepack enable
pnpm install --frozen-lockfile
```

Use the actual frontend build and start scripts from `package.json`. A development server is acceptable for supervised engineering tests, but use a built/preview mode for a repeatable demonstration when the application supports it.

## 4. Configuration and secrets

### 4.1 Configuration contract

Create a local environment/config file using the repository's documented mechanism. Never commit credentials, private camera URLs, API keys, or local filesystem paths containing secrets. Provide a `.env.example` with safe placeholders and keep the live `.env` ignored by Git.

Suggested logical settings (names are illustrative and must be mapped to the implemented settings):

```dotenv
APP_ENV=local
API_HOST=127.0.0.1
API_PORT=8000
DATABASE_URL=sqlite:////absolute/path/to/data/inspections.db
ARTIFACT_DIR=/absolute/path/to/data/artifacts
MODEL_PATH=/absolute/path/to/models/qualified-release
MODEL_VERSION=REPLACE_WITH_VERIFIED_VERSION
DECISION_POLICY_VERSION=REPLACE_WITH_APPROVED_POLICY_VERSION
CAMERA_SOURCE=REPLACE_WITH_VERIFIED_SOURCE
SERIAL_PORT=REPLACE_WITH_VERIFIED_DEVICE
SERIAL_BAUD=REPLACE_WITH_FIRMWARE_BAUD
CONTROLLER_ENABLED=false
LOG_LEVEL=INFO
```

`CONTROLLER_ENABLED=false` is the safe initial condition. Enable physical actuation only after the complete software path, controller protocol, and manual disconnect have been tested. The configuration parser should reject missing required values and invalid paths clearly.

### 4.2 Configuration validation checklist

- [ ] Required keys are present; placeholder values are not accepted as live configuration.
- [ ] Paths are absolute, writable by the runtime user, and outside the Git working tree where appropriate.
- [ ] API bind address is loopback unless access over a private LAN is explicitly needed and protected.
- [ ] Model artifact hash/version matches the release manifest.
- [ ] Decision thresholds/review band come from the approved, evaluated policy release.
- [ ] Camera source is explicit; no silent switch to a different camera.
- [ ] Serial device matches the connected board; no `/dev/tty*` guess.
- [ ] Actuation is disabled during software-only smoke tests.
- [ ] `.env`, local databases, captured images, logs and model weights are ignored by version control where appropriate.

## 5. Storage layout, permissions, and backup

Example runtime layout (adapt to the chosen paths):

```text
~/.local/share/manufacturing-inspection/
  database/inspections.db
  artifacts/original/
  artifacts/heatmaps/
  artifacts/overlays/
  logs/
  backups/
```

Use restrictive permissions for inspection data and logs. Keep image files on disk and reference them from the database rather than storing large image blobs in rows. Store a content hash for each retained image/derived artifact so corruption or mismatch can be detected. Do not delete an artifact while a retained inspection still references it.

For SQLite, verify the implementation's journaling and transaction behavior, serialize write operations where required, and use a supported consistent-backup procedure. Do not copy a live SQLite database file while writes are active and assume the copy is consistent. For the tabletop prototype, define a practical retention limit before capturing many large images; monitor free disk space.

Recommended backup rehearsal:

1. Stop the application cleanly and ensure pending writes/commands are resolved.
2. Back up DB plus artifact directory and release/config manifests to a separate destination.
3. Record backup timestamp, file counts, sizes, and hashes.
4. Restore into a separate test directory, not over the live data.
5. Run integrity checks and retrieve a known inspection with its artifacts.
6. Record pass/fail and the recovery time.

## 6. Camera connection and calibration

### 6.1 Discover capture devices

```bash
lsusb
v4l2-ctl --list-devices
ls -l /dev/video*
ffmpeg -f v4l2 -list_formats all -i /dev/video0
```

Use the actual `/dev/videoN`; do not assume it is `/dev/video0`. A phone may expose a webcam interface only when the phone OS, USB mode, cable, and tools support it. Otherwise use the selected camera bridge application and bind it to a trusted private network. Avoid unencrypted internet-reachable camera streams.

### 6.2 Camera readiness gate

- [ ] Camera is rigidly mounted at a documented height and angle.
- [ ] Inspection region is marked; object is consistently positioned.
- [ ] Focus, exposure, white balance, resolution and frame rate remain stable.
- [ ] Lighting avoids glare, deep shadows and flicker as far as practicable.
- [ ] Capture produces a fresh frame; stale-frame detection is enabled or explicitly tested.
- [ ] Frame dimensions/color channels match model preprocessing expectations.
- [ ] Blur, occlusion, empty frame and under/overexposure tests return a safe result (`UNVERIFIED` or a blocked capture), not an automatic `PASS`.
- [ ] A known-good frame and a known-defect frame are in the test set and their expected outcomes are documented.

Do not re-train or change thresholds to compensate for an uncalibrated camera. First correct focus, lighting, placement and preprocessing consistency; then re-qualify the model/policy if the image distribution changes materially.

## 7. ESP32 connection and actuation enablement

### 7.1 Identify serial port and permissions

```bash
lsusb
ls -l /dev/ttyUSB* /dev/ttyACM* 2>/dev/null || true
dmesg --follow
```

Reconnect the board and observe which device appears. Use the actual serial device node. Depending on the device rules, the access group may be `uucp`, `dialout`, or another configured group. Inspect the device owner/group, add the user to the appropriate existing group if needed, then sign out/in. Do not use world-writable permissions such as `chmod 666` as a workaround.

### 7.2 Safe first connection

1. Set `CONTROLLER_ENABLED=false`.
2. Power the conveyor motor supply off; disconnect motor power while first validating the USB protocol.
3. Confirm firmware identity/version, protocol version, heartbeat/ready state, and error reporting.
4. Verify the application can send a harmless status/STOP/HOLD request and receive a matching ACK.
5. Confirm command IDs are idempotent and duplicate messages do not trigger a second actuation.
6. Test communication loss and controller reset; the UI must show degraded state and physical system must remain stopped/held.
7. With the area clear and under direct supervision, run bounded actuator test cycles using low-risk speed/force settings.
8. Reconnect motor power only after the independent physical disconnect, driver wiring, common ground, supply ratings, and moving-part clearance are checked.

Motor and servo require suitable external drivers/supplies; never power them from ESP32 GPIO. The ESP32 is a bounded executor, not the decision authority. Commands must contain an allowlisted action, unique command ID, and bounded parameters already approved by firmware. The LLM/agent layer must not originate raw actuator control.

### 7.3 Actuation outcome mapping

| Inspection decision | Expected prototype behavior | UI/status requirement |
|---|---|---|
| `PASS` | No reject pulse; release/continue only when policy and machine state permit | Show PASS; actuator status still recorded |
| `FAIL` | Issue at most one bounded reject cycle after persisted decision | Show FAIL and separate action state: pending/acknowledged/completed/failed |
| `UNVERIFIED` | Hold/stop and request manual review; no automatic accept/reject by default | Show amber/manual review; no false success message |
| Controller timeout/unknown state | Stop or hold; do not blindly replay a non-idempotent action | Mark action uncertain and require reconciliation |

## 8. Startup procedure

Start in **software-only mode first**. Use the repository's actual command scripts; the sample service invocation below is illustrative.

### 8.1 Preflight

- [ ] Confirm repository commit and clean/expected working tree.
- [ ] Check disk space, model hash, config, DB/artifact permissions.
- [ ] Verify camera is available and captures a fresh image.
- [ ] Verify model release and decision policy versions are printed in the health/status endpoint.
- [ ] Confirm controller is disabled for the first smoke test.
- [ ] Ensure the physical motor disconnect is accessible and the reject path is clear.

### 8.2 Start local API

For a FastAPI application whose entry point is actually `app.main:app`, an illustrative development command is:

```bash
source .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Replace `app.main:app` with the real entry point. Do not run this command until the repository confirms FastAPI/Uvicorn and that import path. In another terminal, verify the documented endpoints, for example:

```bash
curl --fail http://127.0.0.1:8000/health/live
curl --fail http://127.0.0.1:8000/health/ready
```

Use the actual health routes from Document 07 or the implementation. `live` should indicate process liveness; `ready` should fail if required model, storage, policy, or other dependencies are unavailable. A running process alone does not prove inspection readiness.

### 8.3 Start dashboard

Start the dashboard using the repo's package manager and documented script. Verify that:

- Dashboard API base URL points to the expected local endpoint.
- Status badges distinguish API health, camera health, model readiness, storage health, and controller connectivity.
- Old data cannot appear as a newly completed inspection; timestamps and inspection IDs are visible.
- A command timeout or unknown physical action state is displayed as unresolved, never as completed.

### 8.4 Run a software-only smoke test

1. Submit one known-good sample image through the documented inspection endpoint/UI.
2. Verify the returned inspection ID, terminal outcome, reason code, model/policy versions, and persisted event.
3. Retrieve the inspection again and confirm it survives an API restart.
4. Verify image and heatmap/overlay references resolve and hashes match where implemented.
5. Submit one known-defect sample; compare the result to the qualification record.
6. Submit a corrupt/empty image or simulate model unavailability; verify a safe blocked/`UNVERIFIED` outcome.
7. Confirm no machine command is emitted while controller actuation is disabled.

## 9. Controlled end-to-end startup

Only proceed after software-only tests pass.

1. Clear the belt and reject arm path; put the physical disconnect within reach.
2. Confirm controller firmware version, serial link, sensors, LEDs, and motor-driver state.
3. Keep motor power off and validate STOP/HOLD, status, ACK correlation, and command timeout handling.
4. Enable controller communication but keep motor drive disabled; run a dry-run decision and verify expected command planning.
5. Enable motor supply at the lowest safe setting and test stop/hold first.
6. Run one `PASS` case and confirm no reject actuation.
7. Run one `FAIL` case and confirm exactly one reject cycle and independent action completion acknowledgement.
8. Run one `UNVERIFIED` case and confirm hold/manual-review behavior with no automatic accept/reject.
9. Disconnect USB serial during a test; ensure state becomes unknown/degraded and the system does not issue duplicate actions on reconnect.
10. Record the test run ID, build/release versions, operator, outcome, anomalies, and sign-off.

## 10. Normal operating procedure

### 10.1 Before a batch

- Confirm camera framing/lighting against the reference fixture.
- Confirm model/policy versions and readiness status.
- Confirm adequate storage, DB writable state, and artifact directory availability.
- Verify controller link and interlocks/status if hardware control is enabled.
- Run one known-good check sample and one approved defect check sample according to the qualification plan.
- Confirm the system is not in maintenance, fault, or stale-result state.

### 10.2 Per-item lifecycle

1. Detect/trigger item presence and stop/hold belt as designed.
2. Capture a fresh frame and validate quality.
3. Run inference and deterministic decision policy.
4. Persist decision and event before scheduling the machine action.
5. For PASS, record no-reject outcome and resume only when allowed by the machine state machine.
6. For FAIL, send a unique bounded reject command once; track ACK and physical completion separately.
7. For UNVERIFIED, hold and request authorized human review.
8. Confirm next-item eligibility only after the previous cycle has reached a safe terminal/cleared state.

Operator review must record reviewer identity (where configured), review timestamp, disposition, reason and any override reason. A human override must not rewrite the original model result; preserve both the original decision and subsequent review event.

### 10.3 End of batch

- Stop new item intake, wait for all in-flight inspections/actions to resolve.
- Hold/stop conveyor and physically disconnect motor power before hands-on adjustment.
- Export the session/batch audit data if the workflow requires it.
- Check unresolved `UNVERIFIED`, action-failed and action-unknown records.
- Confirm DB and artifacts have been written; check disk space and logs.
- Record operator notes and defects observed, then shut down services cleanly.

## 11. Shutdown, restart, and recovery

### 11.1 Normal shutdown

1. Disable new inspection triggers.
2. Stop/hold the conveyor; wait for moving parts to stop.
3. Resolve or explicitly mark in-flight inspections and controller commands; do not silently drop state.
4. Persist pending events and close DB connections.
5. Stop API and dashboard using the correct supervisor/terminal.
6. Disconnect actuator power before physical maintenance.

### 11.2 Restart after application crash

- Keep machine power off/hold active until controller state is queried and reconciled.
- Load the persisted inspection and command ledger; identify commands whose final state is unknown.
- Do not blindly replay a reject action unless firmware-side idempotency and reconciliation prove it is safe.
- Reconcile controller status, sensor state and operator-visible item position before resuming.
- Run health/readiness and known-sample checks before re-enabling production of the demo batch.

### 11.3 Failure-response matrix

| Symptom | Immediate action | Diagnose | Resume condition |
|---|---|---|---|
| Camera absent/black/stale | Hold belt; mark inspection unresolved | USB mode, bridge app, device node, focus, stream timestamp | Fresh frame passes validation and reference sample succeeds |
| Model fails to load | Disable automatic decisions; hold | Artifact path/hash, dependencies, memory, model metadata | Correct release loads and known-sample test passes |
| Unexpected score/distribution | Treat item as UNVERIFIED and preserve evidence | Lighting, focus, preprocessing, model/policy version drift | Root cause documented; qualification or approved release restored |
| DB read/write error | Stop new inspections; hold hardware | Permissions, free disk, DB integrity, locks | Durable persistence restored and recovery check passes |
| Artifact missing/hash mismatch | Mark record degraded; no silent success | Path, retention job, disk/storage error | Artifact restored or record handled under explicit retention policy |
| ESP32 disconnected | Stop/hold, controller action state becomes unknown | Cable, serial permissions, board reset, port change | Firmware identity/status confirmed and pending commands reconciled |
| ACK timeout | Do not send duplicate non-idempotent command automatically | Serial logs, command ID, controller state, physical item position | Command outcome resolved by status/reconciliation/operator procedure |
| Dashboard disconnected | Pause new operation if operator can no longer supervise | Browser/API URL, API health, frontend logs | Dashboard state refreshed from server and current machine status confirmed |
| Disk nearly full | Stop capture/intake and hold safely | Artifacts/logs/backup usage, retention rules | Space reclaimed per approved policy and writes verified |
| Power loss | Keep clear of moving parts; isolate supply if safe | Power source, controller boot state, DB recovery | Explicit post-restart reconciliation and smoke tests complete |

## 12. Logs, metrics, and diagnostics

Every inspection should be correlated using a stable `inspection_id` and event/command IDs. Record UTC timestamps (or unambiguous timestamps with timezone), software/build version, model version, policy version, camera identifier, image hash, inference duration, end-to-end latency, outcome/reason codes, persistence status, command IDs, ACK/completion outcomes, and operator review events.

Operational indicators:

- API liveness/readiness and dependency state.
- Capture failure rate, stale-frame count, and frame-quality rejection rate.
- Inference latency (p50/p95), timeouts, and model-load failures.
- Decision counts by outcome and reason code; do not optimize toward fewer UNVERIFIEDs without evidence.
- Controller link uptime, ACK latency, command timeout count, action completion/failure count, and duplicate command suppression count.
- DB write errors, unpersisted event count, free disk space, artifact hash failures, and backup age.

Do not put secrets, access tokens, or unnecessary personal data into logs. Keep event logs append-only at the application level where practical; correction is a new review/correction event, not silent mutation of history.

## 13. Optional development service supervision

For development, separate terminals or a terminal multiplexer are acceptable. For a repeatable local demo, use a service supervisor (for example, systemd user services) only after startup commands, working directory, environment file, restart policy, and logs are verified. Service units must run as the unprivileged application user and should not enable physical actuation automatically on boot.

Operational requirements for a supervised service:

- Explicit working directory and virtual environment/runtime path.
- Environment file with restricted permissions; no secrets embedded in unit files.
- Loopback bind by default; least-privilege access to serial device and data directories.
- Restart-on-failure with backoff, but a restart must not blindly resume a moving conveyor.
- Readiness checks and visible fault state after restart.
- Separate manual actuation enablement step after operator preflight.
- Logs accessible through the service manager and bounded/rotated where appropriate.

Do not copy a generic `systemd` unit into place without adapting and validating `ExecStart`, Python/frontend runtime, environment paths, and user permissions. Never configure startup to automatically start motor motion.

## 14. Security and operational hardening

- Bind to loopback unless remote access is necessary; if LAN access is enabled, use a trusted network, authentication/authorization, firewall controls and documented ports.
- Never expose the local API, development frontend, database, serial bridge, or camera stream directly to the public internet.
- Accept allowlisted image types and enforce request size, pixel dimension, timeout and decode limits.
- Treat image metadata and filenames as untrusted. Use server-generated artifact names and avoid path traversal.
- Restrict model/config write access and verify hashes of released artifacts.
- Do not allow arbitrary shell execution from the dashboard, agent, or API input.
- Enforce role checks on operator review, threshold changes, controller enable/disable and firmware update operations.
- Record policy changes with version, author/operator, timestamp, rationale, and requalification status.
- Keep a manual physical disconnect. Software STOP is not a substitute for isolation before maintenance.
- Do not use real production parts/lines or unsupervised operation during prototype testing.

## 15. Release manifest and demo-day checklist

Fill and retain a release manifest for every validated demo:

| Field | Recorded value |
|---|---|
| Git commit/build ID | ______________________________ |
| Python/frontend runtime versions | ______________________________ |
| Dependency lockfile hash | ______________________________ |
| Model artifact hash/version | ______________________________ |
| Dataset/evaluation report reference | ______________________________ |
| Decision policy version/threshold approval | ______________________________ |
| Firmware version/protocol version | ______________________________ |
| Camera source and fixed setup | ______________________________ |
| DB/artifact path and backup location | ______________________________ |
| Test run ID and sign-off | ______________________________ |

### Demo-day go/no-go

- [ ] Laptop power, spare cable, phone charge, and local network/camera mode are ready.
- [ ] No pending OS/runtime/package upgrade is planned during the demo.
- [ ] Release versions and hashes are recorded; dependencies installed from lockfiles.
- [ ] API and dashboard are reachable only as intended; no public tunnel/port forwarding.
- [ ] Health/readiness checks pass and model is warm-loaded.
- [ ] Test sample set includes known-good, known-defect, and poor-quality/unknown examples.
- [ ] Camera focus, lighting and framing match qualification setup.
- [ ] DB/artifacts writable; storage capacity adequate; backup exists.
- [ ] Firmware version and serial link verified; motor test performed under supervision.
- [ ] Manual power disconnect works and is reachable; moving zone is clear.
- [ ] PASS does not activate reject; FAIL causes at most one reject cycle; UNVERIFIED holds for review.
- [ ] Camera loss, API loss, and serial loss have been demonstrated or tested to lead to safe hold.
- [ ] Known unresolved issues and limitations are disclosed to observers.

If any critical safety, model, persistence, or controller gate fails, do not run the automated physical demonstration. Switch to software-only replay or cancel the moving-hardware portion.

## 16. Acceptance criteria

The installation/runbook is considered operationally validated only when all of the following are evidenced:

1. A clean environment can be installed from recorded versions/lockfiles using documented steps.
2. Startup checks distinguish liveness from readiness and report model, storage and camera/controller status.
3. Local inference produces repeatable results for versioned reference samples within the approved latency target.
4. Missing/corrupt/stale frames, model unavailability and persistence failures cannot default to PASS.
5. Inspection and audit records survive an application restart; artifact hashes/references can be verified.
6. ESP32 protocol tests prove correlation, duplicate suppression, bounded behavior and disconnect handling.
7. Physical tests verify PASS/no reject, FAIL/at most one reject, and UNVERIFIED/hold/manual review.
8. Restart recovery reconciles unknown command states without blind replay.
9. The backup is restored successfully in an isolated location.
10. A supervised operator completes the demo-day checklist and signs the release manifest.

## 17. Known gaps and next actions

Because the actual source repository, camera model, ESP32 board/firmware, motor-driver model, and finalized model release were not available for direct verification when this runbook was drafted, the commands and variable names are examples rather than assertions about the current implementation. Before use, map each step to the real repository and confirm the hardware-specific ratings/pinout from actual component datasheets.

Next actions:

1. Provide or identify the actual repository and audit its README, lockfiles, API entry points, scripts and tests.
2. Replace illustrative module/command names with verified commands; add a tested `.env.example` and one-command preflight script.
3. Record the actual camera and board configuration; verify serial permissions and controller protocol.
4. Define explicit startup/shutdown and recovery ownership for each process.
5. Execute Document 09's integration tests, attach evidence, and use this runbook for a timed rehearsal.
6. Do not claim production readiness until reliability, security, safety and model acceptance criteria are met for the intended environment.

---
**End of Document 10.**
