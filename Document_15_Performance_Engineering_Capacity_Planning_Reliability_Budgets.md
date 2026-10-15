# Document 15 — Performance Engineering, Capacity Planning & Reliability Budgets

**Project:** Agentic AI Smart Manufacturing Quality Inspection & Automation Platform  
**Document type:** Performance and reliability engineering specification  
**Version:** 1.0  
**Status:** Proposed benchmark plan; measured results and current implementation remain unverified  
**Target:** Local-first tabletop prototype using a phone camera, Linux/Arch workstation, anomaly-detection inference, deterministic decision policy, local storage, dashboard, and ESP32-controlled low-voltage hardware.

---

## 1. Purpose

Define how to measure end-to-end performance, determine realistic throughput, locate bottlenecks, and establish reliability budgets for the prototype without compromising inspection validity or actuator safety.

This document deliberately contains **no claimed benchmark numbers** for the current laptop, camera, model, or conveyor. Such numbers must be measured on the actual equipment, code, model artifact, resolution, capture method, and operating conditions.

The initial conveyor workflow stops the belt during capture and inference. Therefore, the practical throughput is determined by the complete stop-inspect-decide-persist-actuate-or-review cycle, not by model inference time alone.

## 2. Performance principles

1. **Measure the whole system:** camera exposure/capture, validation, preprocessing, inference, decision, database/artifact persistence, dashboard update, and any machine-action completion.
2. **Report distributions:** record p50, p95, p99, maximum, sample count, and errors; averages alone hide stalls.
3. **Use the actual path:** phone camera, actual frame resolution, real model artifact, installed dependencies, and intended runtime mode.
4. **Separate modes:** software-only, camera-connected, and supervised hardware runs are different benchmark profiles.
5. **Quality gates first:** never speed up by skipping input validation, reusing stale frames, loosening thresholds without qualification, or pretending `UNVERIFIED` is `PASS`.
6. **Decision versus action:** a `FAIL` decision is not a completed rejection; action completion time must be measured separately.
7. **Repeatability matters:** pin the environment, record configuration, run warm-up, repeat runs, and save raw measurements.
8. **Avoid premature optimization:** profile first, identify the dominant cost, change one thing, and rerun the same benchmark.
9. **Fail closed under overload:** if a valid decision cannot be completed inside the documented operating envelope, use the defined hold/manual-review route.
10. **Prototype scope:** performance results from this supervised tabletop setup do not prove industrial throughput, availability, or functional safety.

## 3. Performance scope and operating modes

### Mode A — Offline/model-only
Uses a fixed, versioned image set and the model runtime. Useful for measuring preprocessing and inference, but it excludes camera latency, physical item synchronization, persistence, and actuator completion.

### Mode B — Live-camera/software-only
Uses the real phone-camera path and local services, with physical actuation disabled. Measures capture-to-durable-decision time and input stability safely.

### Mode C — Supervised tabletop hardware
Uses the real conveyor, presence detection, camera, local decision service, and bounded ESP32 action protocol. The belt stops during capture/inference. This mode measures full cycle time, command handshake, physical settling, and recovery behavior.

### Mode D — Fault/recovery
Injects controlled camera loss, model timeout, database errors, serial disconnection, or restart. Measures detection time, time to hold, recovery duration, and whether state remains traceable. Do not inject faults while a mechanism is moving unless the setup is designed for that test and a supervisor is present.

Always state which mode produced a metric. Never combine mode A latency and mode C throughput into one headline number.

## 4. End-to-end timing model

Record monotonic-clock durations within the process and UTC timestamps for durable events. Do not calculate short stage durations only by subtracting wall-clock timestamps if the system clock may change.

Suggested stages:

1. **T0 — item/frame trigger:** product-presence event or operator request.
2. **T1 — capture complete:** fresh frame is available.
3. **T2 — frame validated:** decode, dimensions, age, and quality gates complete.
4. **T3 — preprocessing complete:** crop/resize/normalize ready for model.
5. **T4 — inference complete:** model output available.
6. **T5 — decision complete:** output validated and deterministic policy applied.
7. **T6 — durable record complete:** inspection row/event and required artifact references are committed.
8. **T7 — dashboard update:** result becomes visible to the operator.
9. **T8 — machine action requested:** only if the policy and mode require an action.
10. **T9 — machine action acknowledged:** firmware accepted the bounded command.
11. **T10 — action completed/reconciled:** completion event or documented physical verification recorded.
12. **T11 — next-item-ready:** mechanism safely returns to the defined ready state.

Derived measurements:
- Capture time = T1 − T0
- Validation/preprocess time = T3 − T1, with T2 retained separately
- Inference time = T4 − T3
- Decision time = T5 − T4
- Persistence time = T6 − T5
- Capture-to-durable-decision = T6 − T0
- Operator-visible response = T7 − T0
- Action handshake = T9 − T8
- Action completion = T10 − T8
- Full cycle time = T11 − T0

Some stages may overlap in a future architecture. If they do, report the actual critical-path end-to-end time and document the overlap rather than summing stage times and treating the sum as the elapsed duration.

## 5. Benchmark environment manifest

Every benchmark run must record:

- run ID, date/time, operator, and test mode;
- source code revision/commit or a clear note that it is unavailable;
- Python/Node/runtime versions, dependency lockfile hash, OS/kernel version;
- CPU model, logical/physical core count if known, RAM, available disk, GPU/accelerator if any;
- power source, power profile, thermal conditions, and whether the laptop is under sustained load;
- model release ID/hash and exact preprocessing configuration;
- model backend/device and precision where applicable;
- dataset ID/version, image hashes, input count, and split role;
- camera source/app/connection type, resolution, FPS settings, orientation, exposure/focus/lighting setup;
- ESP32 firmware build/version and connection method for hardware mode;
- database backend/schema version, artifact storage path class, and logging level;
- warm-up count, measured repetition count, concurrency, retry behavior;
- any exclusions, errors, restarts, or manual interventions.

A benchmark without this manifest is exploratory evidence only and should not be used to compare releases conclusively.

## 6. Benchmark protocol

1. Select one benchmark profile and freeze configuration.
2. Verify the model release, preprocessing version, policy version, camera configuration, and dataset manifest.
3. Confirm sufficient disk space and no unrelated heavy workload.
4. Start with a small smoke test to confirm correct IDs, frame freshness, persistence, and mode.
5. Run a documented warm-up phase to allow model loading, caches, and CPU/GPU frequency behavior to settle.
6. Execute the planned measurement set without changing settings mid-run.
7. Capture one record per inspection, including stage timings, result, error code, model/policy versions, and action state.
8. Include failed and `UNVERIFIED` cases in reliability results; do not discard them to make latency look better.
9. Repeat the benchmark across multiple runs or sessions and, where relevant, cold-start and warm-start conditions.
10. Compute p50/p95/p99, maximum, count, error rate, throughput, and the number of manual interventions.
11. Inspect outliers; classify them rather than automatically deleting them.
12. Save raw CSV/JSONL data, manifest, summary report, plots, and artifact hashes.
13. Compare candidate releases with the same fixed profile and dataset.
14. Re-run the integration tests after material performance changes.

The number of repetitions should be large enough to represent expected variation and tail behavior. Choose and document it based on the intended claim; do not treat a tiny run as a reliable p99 estimate.

## 7. Required performance metrics

| Area | Measurement | Why it matters |
|---|---|---|
| End-to-end | Trigger-to-durable-decision and trigger-to-ready cycle | Measures real item cycle, not model-only speed |
| Stage latency | Capture, validation, preprocessing, inference, decision, persistence, UI, action | Identifies the critical bottleneck |
| Tail latency | p50/p95/p99/max and sample count | Reveals stalls hidden by the average |
| Throughput | completed inspections per minute/hour by mode | Reflects actual stop/start and review behavior |
| Availability | ready time, degraded time, blocked time, planned maintenance | Avoids confusing uptime with successful inspection |
| Reliability | failed, retried, `UNVERIFIED`, duplicate, stale-frame and persistence-error counts | Detects correctness and reliability problems |
| Resource use | CPU, RAM, disk I/O, disk free space, thermal throttling, GPU/VRAM if applicable | Explains slowdowns and resource pressure |
| Camera | frame age, capture timeout, reconnect count, invalid-frame rate | Guards against stale or missing input |
| Database/artifacts | transaction/write latency, errors, queue depth, artifact size | Protects traceability |
| Machine action | ACK latency, completion latency, timeout/unresolved count | Separates model decisions from physical outcomes |
| Recovery | fault-detection time, hold time, recovery time, unreconciled states | Measures failure response rather than only ideal runs |

Report rates with denominators, e.g. “invalid frames / capture attempts,” rather than percentages without counts.

## 8. Throughput and capacity planning

For the stop-during-inspection prototype, estimate capacity using the **measured full cycle**.

If the conveyor is held until the next-item-ready point, the theoretical serial rate is:

\[
\text{items per second} = \frac{1}{\text{mean full cycle time in seconds}}
\]

\[
\text{items per minute} = \frac{60}{\text{mean full cycle time in seconds}}
\]

This is only a planning estimate. Sustainable throughput must also account for variability, product spacing, operator review, failures, setup changes, mechanical settling, and planned downtime. Use p95/p99 cycle time for delay/spacing safety considerations, not only the mean.

### Worked example (illustrative arithmetic only)
If a measured full cycle happened to be **4.0 seconds**, the idealized serial upper bound would be 15 items/minute before any additional downtime, manual review, or safety margin. This number is an example to explain the formula, **not a performance claim or target for the actual prototype**.

### Capacity worksheet
Record:
- measured mean full-cycle time;
- p50/p95/p99 full-cycle time;
- average review/hold time;
- fraction of items routed to manual review;
- observed camera/model/persistence/action failures;
- available operating time per session;
- planned setup/calibration and maintenance time;
- target volume and acceptable queue age;
- required engineering margin, justified by the test plan.

If an item is sent to manual review, treat that path as its own cycle and capacity class. Do not assume its time is the same as a normal `PASS`.

## 9. Reliability budgets and error accounting

Do not choose arbitrary numeric reliability targets without a workload and risk statement. Define explicit budgets before qualification.

### 9.1 Outcome integrity budget
For valid test cases:
- no invalid or missing input becomes `PASS`;
- no stale result is applied to a new item;
- no duplicate retry causes an uncontrolled second physical action;
- no inspection is reported durably complete when persistence did not succeed;
- no model/policy version mismatch is silently ignored.

These are correctness invariants, not average-rate goals; one violation blocks release until investigated.

### 9.2 Operational error budget
For non-safety availability targets, define:
- observation window;
- permitted failed/degraded minutes or inspection failures;
- included/excluded planned maintenance;
- denominator and source of truth;
- burn-rate or escalation rules, if suitable for the scale;
- action when the budget is exhausted.

For the early tabletop prototype, a run-level scorecard may be more useful than sophisticated burn-rate monitoring. Every `UNVERIFIED`, failed persistence attempt, serial timeout, or manual intervention must be counted and categorized.

### 9.3 Reliability scorecard
Suggested run-level fields:
- total requested inspections;
- valid captures / rejected captures;
- model successes / model errors / timeouts;
- durable decisions / persistence failures;
- PASS / FAIL / UNVERIFIED counts;
- decisions routed to manual review;
- machine commands issued / ACKed / completed / timed out / unresolved;
- duplicate commands suppressed;
- false accept / false reject findings, only when ground truth is available;
- restarts and recovery incidents;
- p50/p95/p99 of each critical stage;
- start/end free disk and maximum observed memory/CPU/temperature if available.

Keep these metrics distinct. A low error count is not proof of good defect detection, and a high `FAIL` count is not proof of poor product quality.

## 10. Performance constraints that must not be optimized away

Never improve headline speed by:
- skipping image decode/validity checks;
- reusing stale or previously inspected frames;
- applying a previous item’s decision to the current item;
- skipping durable persistence where traceability is required;
- bypassing model-output validation;
- changing thresholds without a new policy version and qualification;
- silently dropping errors or `UNVERIFIED` samples from the benchmark;
- launching the next item before the physical state is known;
- replaying non-idempotent machine actions to mask timeouts;
- letting an LLM directly choose arbitrary actuator parameters.

If latency is too high, optimize measured bottlenecks, use a qualified lighter model/runtime, or revise the operating envelope. Any model/preprocessing/threshold change must be re-evaluated for quality.

## 11. Profiling workflow for the Linux workstation

### Step 1 — Establish a baseline
Capture CPU, RAM, disk, thermal behavior, model load time, warm inference time, and end-to-end timings. Record whether the laptop is on battery or power and its performance profile.

### Step 2 — Locate the dominant stage
Compare stage p50/p95 values. If inference dominates, profile preprocessing and model execution. If capture dominates, inspect camera transport and capture configuration. If persistence dominates, inspect transaction duration and artifact I/O. If latency has long outliers, inspect OS scheduling, thermal throttling, contention, and blocking operations.

### Step 3 — Profile one layer at a time
- **Python/application:** use targeted timers and a profiler appropriate to the code path.
- **CPU/RAM:** use OS process/system monitors; collect repeatable snapshots.
- **Disk:** measure artifact write and database transaction time; avoid logging huge payloads.
- **Camera:** measure trigger-to-frame age and reconnect/timeout rates.
- **Model:** separate load/warm-up/preprocessing/inference/postprocessing.
- **Serial:** measure issue-to-ACK and issue-to-completion separately.
- **Thermals:** repeat sustained tests; do not report only the first fast run.

### Step 4 — Change and compare
Make one change, keep the same test data and environment, record a new manifest, and compare distributions plus error rates. Revert any change that improves speed but violates input validity, model quality, auditability, or action integrity.

### Step 5 — Check the tail
Investigate the slowest cases individually. A high p99 may indicate a camera stall, cold load, disk sync, thermal drop, or serial issue. Do not delete those cases unless they are proven measurement errors and the exclusion is documented.

## 12. Candidate optimization areas

Only attempt after profiling:
- load the model once per service lifecycle rather than per inspection;
- avoid repeated initialization and redundant image conversions;
- validate image dimensions early and reject unsupported inputs promptly;
- reuse bounded preprocessing buffers only if correctness and thread safety are maintained;
- make artifact writing efficient without removing required evidence;
- tune thread counts or runtime backend empirically;
- use reduced precision or accelerator paths only after numerical and quality regression tests;
- cache immutable configuration/model metadata, not prior item decisions;
- reduce unnecessary high-frequency dashboard polling;
- keep logging structured but avoid synchronous verbose debug logs on the critical path;
- decouple noncritical report generation from the critical inspection path while preserving durable event commit semantics.

Any asynchronous queue or parallel pipeline must preserve the association between physical item, captured frame, decision, and action. Do not introduce pipelining until item identity and sequence control are explicitly tested.

## 13. Overload and degraded-mode behavior

Define and test these responses:
- **Inference queue full:** backpressure/hold; do not silently drop a physical item.
- **Inference timeout:** `UNVERIFIED`, preserve reason, no stale result fallback.
- **Disk below critical threshold:** stop admitting new inspections that require durable evidence.
- **Camera disconnected:** mark not ready for live inspection.
- **ESP32 unavailable:** software-only mode may be permitted for tests, but hardware mode remains not ready.
- **Unresolved machine command:** block the next hardware cycle until reconciled.
- **UI unavailable:** local API and safe controller behavior must remain defined; do not depend on the dashboard as the only physical stop mechanism.
- **High CPU or thermal throttling:** alert or hold if the measured operating envelope is exceeded; do not lower validation standards automatically.
- **Agent/LLM unavailable:** deterministic inspection must continue if agents are optional; if an agent is part of a required decision path, fail according to the validated policy—not by guessing.

## 14. Benchmark report template

Each report should include:

### Summary
- Purpose and run mode.
- Tested code/model/policy/firmware revisions.
- Hardware and environment.
- Test date/operator.
- Pass/fail status against predeclared criteria.

### Results
- sample count and excluded cases;
- latency table: p50/p95/p99/max and units;
- throughput by mode;
- failure and `UNVERIFIED` counts with denominators;
- CPU/RAM/disk/thermal summary;
- camera and serial health;
- known limitations and outliers.

### Evidence
- benchmark manifest;
- raw JSONL/CSV records;
- scripts/commands and dependency lockfile;
- plots and summary;
- artifact hashes;
- reviewer/approval.

### Decision
- accepted for the specific intended mode, rejected, or exploratory only;
- required corrective action;
- expiry/review trigger after material hardware/software/configuration changes.

## 15. Implementation roadmap

### Phase A — Timing and measurement foundation
- Add monotonic stage timers and UTC event timestamps.
- Persist stage durations with inspection IDs.
- Record model/policy/camera/firmware versions and outcome reasons.
- Add a repeatable benchmark script and raw JSONL/CSV export.

### Phase B — Baseline profiles
- Measure offline, camera-connected software-only, and supervised tabletop modes separately.
- Capture warm/cold behavior, resource use, and error rates.
- Establish realistic targets only after observing distributions.

### Phase C — Capacity and reliability
- Add full-cycle throughput calculation and manual-review capacity.
- Add reliability scorecard and correctness invariants.
- Define run-level operational budgets and alert thresholds.

### Phase D — Optimization and regression
- Profile dominant stages.
- Apply one optimization at a time.
- Rerun fixed benchmark and quality/integration test suites.
- Preserve results for release comparison.

### Phase E — Operational hardening
- Test overload, disk exhaustion, restarts, camera loss, serial loss, and model timeout.
- Verify safe hold, clear operator visibility, and no stale/duplicate action.
- Document the exact envelope within which the prototype is approved to operate.

## 16. Acceptance checklist

- [ ] Benchmark results are tied to code, model, policy, camera, dataset, and firmware versions.
- [ ] Offline, camera-connected, hardware, and fault-recovery modes are reported separately.
- [ ] Stage durations and end-to-end cycle time use suitable clock sources.
- [ ] Latency includes p50/p95/p99/max and sample count.
- [ ] Failed and `UNVERIFIED` cases are counted rather than discarded.
- [ ] Full-cycle throughput accounts for stop/start, action completion, and manual review.
- [ ] Reliability correctness invariants are release blockers.
- [ ] No optimization bypasses validation, persistence, decision governance, or physical-state reconciliation.
- [ ] Overload behavior is explicit and tested.
- [ ] A reproducible benchmark manifest and raw measurements are retained.
- [ ] Numeric performance SLOs are based on measured baseline and intended use.
- [ ] Candidate performance changes pass model-quality and integration regression tests.

## 17. Open decisions

Resolve after measuring the actual system:
- CPU, memory, GPU/accelerator availability and thermals.
- Camera mode/resolution and measured capture delay.
- Actual model runtime, warm-up, inference and postprocessing costs.
- Required operating volume and tolerable review/hold rate.
- Whether model, camera, and hardware processing can overlap safely.
- Required evidence durability and storage budget.
- Numeric latency and availability SLOs, with rationale.
- Measured full-cycle time and mechanical settling constraints.
- Acceptable fault-recovery time for the intended supervised demo.

## 18. Final rule

Performance engineering must improve measured bottlenecks while preserving correct item identity, valid input, deterministic decisions, durable records, and bounded hardware actions. The true unit of performance is a correctly completed and traceable inspection cycle—not a fast model call in isolation.
