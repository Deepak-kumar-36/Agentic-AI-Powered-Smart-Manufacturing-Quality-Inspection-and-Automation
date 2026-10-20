# Project TODO and Completion Checklist

**Reviewed:** 2026-10-17 (Asia/Calcutta)
**Scope:** Documents 01–17, the production PRD, repository implementation, Kaggle EfficientAD-S run, and current automated checks.

Legend: `[x]` verified complete, `[~]` implemented or partially evidenced, `[ ]` remaining, `[!]` blocked by an external dependency or decision.

## 1. Reproducible software foundation

- [x] Pin the Python runtime with `.python-version` and project metadata.
- [x] Keep a lockfile: `requirements.lock`.
- [x] Provide a Dockerfile that installs the project and runs the offline tests.
- [x] Provide one offline test command: `make test`.
- [x] Keep secrets, datasets, checkpoints, and generated artifacts out of Git.
- [x] Keep an `.env.example` without secrets.
- [x] Keep the repository on a working Git branch with incremental commits.
- [x] Run the current test suite: 43 tests, 40 passed, 3 expected skips.
- [x] Run Python compilation and `git diff --check`.

## 2. Deterministic decision and persistence core

- [x] Restrict terminal outcomes to `PASS`, `FAIL`, and `UNVERIFIED`.
- [x] Fail closed for invalid images, stale input, unavailable models, incompatible versions, invalid scores, and review-band scores.
- [x] Implement versioned deterministic threshold policies with boundary tests.
- [x] Persist inspections transactionally in SQLite.
- [x] Persist immutable inspection events.
- [x] Enforce idempotency keys and request-hash conflict detection.
- [x] Verify persistence read-back and idempotency behavior with tests.
- [x] Keep client-provided scores and outcomes untrusted.
- [x] Store additive human review records separately from AI decisions, with audit events and provenance where available.

## 3. Local API and operational path

- [x] Implement liveness and readiness endpoints.
- [x] Implement system status and inspection resource endpoints.
- [x] Implement a reusable HTTP server factory.
- [x] Add an end-to-end local HTTP smoke test.
- [x] Add path-root enforcement for request images.
- [x] Add the reviewed EfficientAD server CLI: `python -m app.serve`.
- [x] Add category-specific model policy evaluation in the API.
- [x] Add offline stored-image capture-to-decision workflow with restart tests.
- [x] Add model cache reuse across requests.
- [x] Add explicit per-category/all-category model cache reload.
- [ ] Add structured production logging and correlation IDs.
- [ ] Add request authentication/authorization if LAN or multi-user access is approved.
- [ ] Add durable API process/service packaging beyond the test-oriented Docker command.

## 4. EfficientAD-S model qualification

- [x] Implement native EfficientAD-S teacher/student/autoencoder inference.
- [x] Use the cited frozen reference teacher artifact.
- [x] Add checkpoint metadata and teacher hash validation.
- [x] Add category-specific checkpoints for `bottle`, `screw`, and `capsule`.
- [x] Complete the 70,000-step Kaggle training run for all three categories.
- [x] Export validation-derived thresholds and untouched-test metrics.
- [x] Export image AUROC, precision, recall, F1, pixel AUROC, and latency metrics.
- [x] Preserve the Kaggle dataset manifest and checkpoint hashes locally.
- [x] Run real local inference with all three downloaded checkpoints.
- [ ] Review score distributions and choose explicit PASS/review/FAIL operating thresholds.
- [ ] Set `qualification_status` to `QUALIFIED` only after threshold review and artifact review.
- [ ] Load the reviewed release through `load_reviewed_release`.
- [ ] Run the real model-backed HTTP API using approved thresholds.
- [ ] Add a local calibration report that records the threshold rationale and false-accept/false-reject tradeoff.

## 5. Dataset and model governance

- [x] Validate the MVTec directory layout and image/mask integrity.
- [x] Generate a deterministic hashed dataset manifest.
- [x] Preserve dataset license/provenance metadata.
- [x] Keep train/validation/test separation in the workflow.
- [x] Keep final test data out of threshold calibration.
- [ ] Add explicit grouped-leakage checks for every future product/category dataset.
- [ ] Add a signed or owner-approved model release record.
- [ ] Define artifact retention and rollback policy.

## 6. Camera and capture

- [ ] Decide the camera/phone device and transport protocol.
- [x] Define a hardware-neutral capture adapter contract with frame identity and capture timestamps.
- [x] Add stale-frame, replayed-sequence, malformed-image, and freshness tests.
- [x] Implement the Linux V4L2 adapter through an isolated ffmpeg raw-frame process.
- [x] Implement a runtime-configured local-network MJPEG adapter for phone cameras.
- [x] Add a phone-camera smoke-test CLI that writes only an explicitly chosen local frame artifact.
- [x] Add a supervised, read-only phone shadow-inference loop using the existing API/model/policy path.
- [ ] Confirm whether `/dev/video0` is the intended inspection camera or replace it with the selected phone/UVC source.
- [ ] Verify the chosen phone app's MJPEG endpoint and run the shadow loop while the phone is online.
- [ ] Run the camera-only acceptance matrix across three independent start/stop sessions.
- [ ] Measure camera-to-decision latency on the target workstation.
- [ ] Verify lighting, framing, focus, and defect visibility for the selected product.

## 7. Dashboard and operator workflow

- [x] Define a dependency-free browser dashboard against the existing HTTP API contract.
- [x] Build status, inspection history, evidence, and event timeline views.
- [x] Add local image upload into the configured API image root.
- [ ] Keep visual outcome separate from physical action state.
- [x] Add accessible operator states and clear API error handling.
- [~] Add frontend smoke coverage against the real API contract; full browser automation remains open.
- [x] Add dashboard human review submission, validation, and chronological review history.
- [x] Add backend review coverage, latest-review agreement/disagreement, conflict, and attention analytics.

## 8. ESP32, machine actions, and safety

- [x] Keep actuation disabled by default in the current software slice.
- [ ] Decide the ESP32 board, motor, driver, servo, sensors, and exact wiring.
- [ ] Implement a bounded, versioned, idempotent host-side protocol simulator.
- [ ] Implement ACK versus completion semantics.
- [ ] Add duplicate, malformed, timeout, disconnect, and physical-stop tests.
- [ ] Add firmware source/build and hardware-in-the-loop evidence.
- [ ] Do not enable actuation before Gate C supervised evidence.

## 9. Observability, performance, and reliability

- [ ] Implement structured logs with redaction and correlation fields.
- [ ] Add low-cardinality metrics for capture, inference, decisions, persistence, and actions.
- [x] Record model inference latency in the Kaggle evaluation output.
- [ ] Add full-cycle latency measurements from capture through durable decision.
- [ ] Define baseline and alert thresholds from real workloads.
- [ ] Add queue/backpressure and disk-full behavior tests.
- [ ] Add incident playbooks and operator reconciliation flows.

## 10. Backup, disaster recovery, and continuity

- [x] Document 16 is now present in the workspace and available for review.
- [ ] Define the authoritative backup set: code, database, model release, policy, preprocessing, configuration, and firmware.
- [ ] Implement local backup creation with consistent manifests.
- [ ] Test clean-location restore.
- [ ] Test corrupted/missing model artifact recovery.
- [ ] Test database restore and event-history integrity.
- [ ] Define RPO/RTO targets and retention policy.
- [ ] Verify recovery never resumes motion without supervised reconciliation.

## 11. Readiness gates

- [x] Gate A software slice: local tests and software-only HTTP path verified.
- [~] Gate A model qualification: full EfficientAD run and local inference verified; release approval remains open.
- [!] Gate B live camera: blocked until camera hardware/transport is selected and tested.
- [!] Gate C supervised tabletop hardware: blocked until firmware, protocol, hardware, and safety evidence exist.
- [ ] Gate D pilot readiness: requires Gate B/C evidence, monitoring, recovery, and operator training.
- [ ] Gate E production readiness: requires security, backup/restore, release rollback, support, and go/no-go approval.

## Immediate next actions

1. Review the updated Kaggle score-distribution output after the notebook completes.
2. Choose and document per-category operating thresholds; do not optimize thresholds on the test set.
3. Change release metadata to `QUALIFIED` only after that review.
4. Start the local API through `python -m app.serve` with the approved thresholds.
5. Add a real-image API smoke test using one downloaded image under the configured image root.
6. Decide the camera path before starting dashboard or hardware work.

## Evidence sources

- `docs/PROJECT_DOCUMENT_INDEX.md`
- `docs/REQUIREMENTS_TRACEABILITY.md`
- `docs/IMPLEMENTATION_ROADMAP.md`
- `docs/DECISIONS_AND_OPEN_QUESTIONS.md`
- `docs/REPOSITORY_AUDIT.md`
- `docs/BASELINE_TEST_REPORT.md`
- `Document_01_Project_Charter_Execution_Roadmap.md` through `Document_17_Production_Readiness_Go_No_Go_Assessment.md`
- `Production_Grade_Agentic_Manufacturing_Quality_Inspection_PRD.md`
- `app/`, `tests/`, and the Kaggle artifact bundle under `artifacts/efficientad_s_release/`
