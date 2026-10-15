# Document 11 — Model Monitoring, Drift Detection & Continuous Improvement Plan

**Project:** Agentic AI Smart Manufacturing Quality Inspection & Automation Platform  
**Document type:** Engineering specification and operating procedure  
**Version:** 1.0  
**Status:** Proposed design — implementation must be verified against the actual repository  
**Deployment target:** Local-first tabletop prototype using a phone camera, Linux/Arch workstation, PatchCore-style anomaly detection, local persistence, and ESP32-based low-voltage actuation.

---

## 1. Purpose

Define how the platform will measure inspection quality over time, identify changes in input conditions or model behavior, investigate questionable outcomes, and promote model or policy changes without silently weakening inspection controls.

This document does **not** claim that monitoring, drift detection, model registry, or retraining workflows already exist. They are target capabilities until the source repository and running system are inspected.

## 2. Operating principles

1. **No silent model changes.** Every inspection records an immutable model release ID and decision-policy version.
2. **Unknown is not good.** Missing images, invalid frames, unavailable models, incompatible preprocessing, or incomplete inference must produce `UNVERIFIED`, not `PASS`.
3. **Separate signal types.** Input/camera drift, model-score drift, confirmed quality outcomes, and actuator faults are different signals and must not be conflated.
4. **No automatic production promotion.** Drift alerts can request review; they cannot change thresholds, deploy a model, or alter actuator behavior on their own.
5. **Use ground truth where possible.** Anomaly scores alone do not establish whether a product is defective.
6. **Preserve traceability.** Keep the source image or approved artifact reference, hashes, outcome, score semantics, model/policy versions, and any human review.
7. **Prototype first, industrial controls later.** This monitoring design is for a supervised low-voltage tabletop prototype and is not a certified industrial quality or safety system.

## 3. Scope and boundaries

### In scope
- Camera and image-quality telemetry.
- Inference latency, errors, score distributions, and outcome rates.
- Drift indicators and review queues.
- Operator feedback and ground-truth capture.
- Model/policy release metadata and rollback.
- Periodic review, incident response, and reporting.

### Out of scope for the initial prototype
- Autonomous model retraining or deployment.
- Automatically changing decision thresholds from live data.
- Claiming statistical process control capability without a defined process and adequate sampling.
- Direct LLM control of motors, servo angles, or decision thresholds.
- Replacing certified safety systems, calibrated metrology, or a validated manufacturing quality process.

## 4. What must be monitored

| Signal group | Examples | Why it matters | Initial action |
|---|---|---|---|
| Camera/input quality | frame missing, blur proxy, exposure, brightness, resolution, crop/scale, color shifts | Input changes can invalidate the baseline | Mark affected inspection `UNVERIFIED`; investigate camera setup |
| Model runtime | inference duration, timeout, exception, model-load status, device/backend | Detects failures and latency regressions | Fail closed; alert operator |
| Model outputs | anomaly score distribution, heatmap coverage, score percentiles by product/shift/camera setup | Detects behavior changes, not necessarily quality defects | Compare against a qualified baseline; request review |
| Decision outcomes | PASS/FAIL/UNVERIFIED counts and rates, review overrides | Shows operational changes and possible policy problems | Check denominators and context; do not infer quality from rates alone |
| Confirmed quality | operator-confirmed defect type, false accept, false reject, rework/inspection result | Needed to estimate real quality performance | Track only with defined labeling procedure |
| Hardware execution | ESP32 ACK, command completion, reject-cycle result, sensor disagreement, timeouts | Separates decision correctness from physical action | Stop or hold prototype workflow; reconcile command state |
| System operations | API availability, disk free space, DB errors, clock drift, queue age, sync failures | Protects traceability and reliability | Alert; preserve logs and recover safely |

## 5. Required inspection telemetry

Each inspection record should include, where available:

- `inspection_id` and correlation/request ID.
- UTC timestamps for capture, inference start/end, decision, persistence, and actuator completion.
- Product/category and line/station identifier, once selected.
- Camera source ID, frame dimensions, capture method, and camera configuration revision.
- Image artifact reference and cryptographic hash; avoid placing large image bytes in the database.
- Image-quality measurements and validation result.
- Model name, immutable model release ID, weights/artifact hash, preprocessing version, feature extractor/backbone, and runtime version.
- Raw anomaly score with explicit score semantics and units; never label it a probability unless calibrated and validated as one.
- Decision-policy version, threshold configuration revision, final `PASS` / `FAIL` / `UNVERIFIED`, and reason codes.
- Inference latency and processing errors.
- Operator review outcome, reviewer identity/role where appropriate, review timestamp, and evidence source.
- Machine command ID, idempotency key, ESP32 firmware version, ACK/completion state, and any fault.
- Data-retention classification and whether an image is eligible for training/requalification.

Missing fields must be represented explicitly as missing/unknown, not filled with guessed defaults.

## 6. Baseline and qualification window

Before enabling alerts, capture a controlled baseline using a fixed, documented setup.

### Baseline record
- Product/category and expected operating conditions.
- Camera model/source, mounting position, working distance, lighting, focus, exposure, resolution, crop, and image preprocessing.
- Model release ID and hash; policy version and threshold values.
- Dataset identity and split protocol used for qualification.
- Number of known-good and known-defective samples, source of labels, and known limitations.
- Score distribution summaries, latency percentiles, image-quality ranges, outcome rates, and failure counts.
- Evaluation results and acceptance decision, with reviewer/date.

Do not invent a universal sample count or acceptable defect rate. Choose sample size based on defect risk, expected variability, and the intended claim; record the rationale. If labels are weak or the product category is still undecided, describe the baseline as exploratory rather than qualified.

## 7. Drift taxonomy and detection

### 7.1 Input / camera drift
Examples include a moved phone, changed lighting, focus changes, different exposure, a new crop, altered image resolution, dirty lens, or a different capture application.

Candidate indicators:
- Resolution and aspect-ratio mismatch.
- Brightness and contrast summary shifts.
- Blur/sharpness proxy outside the qualified range.
- Saturation/color histogram shift.
- Invalid/corrupt frame rate.
- Change in camera source or capture configuration revision.

These checks should be treated as **input validity checks** first. If a frame falls outside validated capture constraints, mark it `UNVERIFIED`; do not rely on the model to compensate for an unknown camera setup.

### 7.2 Model-score drift
Track score distributions by relevant context: product type, camera setup, lighting configuration, and time window. Use robust summaries such as median and upper percentiles, plus sample counts. Do not pool unrelated product categories.

A score-distribution change is an investigation trigger, not proof of new defects. Potential causes include input drift, product mix changes, software changes, or genuine process changes.

### 7.3 Outcome / quality drift
Track confirmed false accepts, false rejects, defect-type counts, and rework results when reliable labels are available. Include denominator and label source. A rise in `FAIL` alone does not establish worsening quality; it could reflect a camera or threshold change.

### 7.4 Runtime / action drift
Track latency percentiles, exceptions, model load failures, stale frame detections, serial disconnects, ESP32 ACK/completion timeouts, and duplicate command attempts. These are operational reliability signals and should have independent alerts.

### 7.5 Statistical caution
- Establish a baseline and context before choosing alert limits.
- Require a minimum sample count before interpreting a distribution.
- Account for repeated measurements and changing product mix.
- Avoid p-value-only alerts or repeated uncorrected testing across many features.
- Record the window, metric, baseline, current sample count, and reason for every alert.
- For the early tabletop prototype, simple descriptive limits and manual review are preferable to an overengineered drift platform.

## 8. Alert levels and response

| Level | Example | Required response |
|---|---|---|
| P0 — Safe hold | image/model validity failure, ambiguous command state, unexpected actuator behavior | Hold belt/inspection flow; mark affected item `UNVERIFIED`; operator intervention |
| P1 — Quality concern | confirmed false accept, sustained input drift, score shift beyond approved guardrail | Pause model/policy promotion; review samples and setup; document disposition |
| P2 — Runtime degradation | repeated inference errors, latency regression, growing queue, low disk space | Investigate logs/resources; recover service without changing quality policy |
| P3 — Advisory | small score-distribution change with adequate input validity and no confirmed quality signal | Log and review in scheduled analysis; no automatic action |

Exact numeric thresholds must be selected after baseline collection and documented with owner, rationale, and expiry/review date. Do not copy generic thresholds into a live quality process without qualification.

## 9. Operator review and ground-truth workflow

1. An alert or operator concern creates a review item linked to the inspection ID.
2. Preserve the original decision, score, policy/model versions, image hash, and action state.
3. A reviewer examines the original image and any heatmap with the applicable review instructions.
4. Record one of: `CONFIRMED_DEFECT`, `CONFIRMED_GOOD`, `INCONCLUSIVE`, `LABEL_ERROR`, or a controlled category-specific label.
5. Record defect class and evidence source where relevant.
6. If evidence is inconclusive, keep it out of training labels and mark it for follow-up.
7. Any manual disposition is an auditable human action; it must not rewrite the original model result.
8. For physical hardware, reconcile the actual reject/hold outcome independently of the visual quality label.

Do not use model-generated labels as ground truth for the same model’s evaluation.

## 10. Model and policy release management

Each release must have an immutable manifest containing:

- Release ID and creation timestamp.
- Model architecture and library/runtime versions.
- Weights/artifact hash and artifact storage location.
- Feature extractor/backbone and layers used, if applicable.
- Image preprocessing and normalization version.
- Training/normal-data dataset IDs, data provenance, splits, and licensing notes.
- Threshold/policy version stored separately from model weights.
- Qualification report, test results, known limitations, approver, and rollback target.

### Promotion sequence
1. Build candidate in an isolated workspace.
2. Run data and artifact integrity checks.
3. Evaluate on fixed holdout data that was not used to fit memory banks or tune thresholds.
4. Run camera-condition and nuisance-condition tests.
5. Run regression tests against the currently qualified release.
6. Run shadow/offline comparison without actuator effects.
7. Approve release and record the operator/owner.
8. Deploy with an explicit version change and a rollback path.
9. Monitor the new release under increased review.
10. Revert if release gates fail or a material quality regression is confirmed.

Never overwrite a qualified artifact in place. Store each release by immutable ID/hash.

## 11. Threshold and decision-policy governance

- Thresholds are versioned configuration, not hidden constants or LLM output.
- Threshold changes require evaluation on the qualified validation/holdout protocol and approval.
- Store the exact threshold and policy revision with every inspection.
- Do not tune thresholds against the final test set repeatedly.
- Define behavior at the exact boundary (`<`, `<=`, `>`, `>=`) and test it.
- If the model score is outside a validated operating range, image validity fails, or policy configuration cannot be loaded, return `UNVERIFIED`.
- `UNVERIFIED` means no automatic accept/reject conclusion; the operator follows the defined hold/manual-review path.
- An inspection outcome and physical actuator outcome remain separate state fields.

## 12. Storage, privacy, and retention

- Store telemetry in the durable inspection database; keep large images and heatmaps as files or object artifacts with hashes and references.
- Use atomic writes and transactional inspection/event persistence.
- Maintain an append-only event history for decisions, reviews, releases, and actuator commands.
- Define retention periods for images, heatmaps, telemetry, and audit events based on the project’s needs and applicable obligations.
- Restrict image and operator access; avoid collecting people or unrelated background content.
- Provide disk-space alerts and a tested backup/restore procedure.
- Never delete the only evidence for an unresolved incident as part of automatic cleanup.
- If cloud sync is added later, local inspection must remain functional when offline; sync status must be visible and retriable.

## 13. Dashboard and reporting requirements

Recommended views:
- Current model release and decision-policy version.
- Inspection counts and PASS/FAIL/UNVERIFIED rates with time window and denominator.
- Inference latency p50/p95/p99 and error count.
- Input-quality warning counts and camera configuration changes.
- Score distribution summary compared with the selected baseline.
- Confirmed false-accept/false-reject counts, with label coverage.
- Review queue age and unresolved incidents.
- ESP32 ACK/completion failures and action reconciliation.
- Disk space, database health, model readiness, and sync backlog.
- Release history and qualification status.

Dashboard labels must distinguish measured facts from inferred alerts. Do not show a single “accuracy” percentage unless the ground-truth dataset, label quality, denominator, and metric definition are explicit.

## 14. Incident response playbooks

### Camera moved or lighting changed
1. Hold automatic decisions.
2. Mark affected inspections `UNVERIFIED` from the time the change is detected, if the affected range can be identified.
3. Restore the qualified camera/lighting setup.
4. Capture a reference set and compare with the baseline.
5. Resume only after image-quality checks pass and the responsible operator records approval.

### Score distribution shifts
1. Verify model and policy versions did not change unexpectedly.
2. Compare input-quality telemetry and product mix.
3. Sample and review images using an independent procedure.
4. Confirm labels before claiming quality degradation.
5. Document the cause and decide whether requalification is required.

### Model load or inference failure
1. Fail closed; do not reuse a stale prior result.
2. Mark the affected inspection `UNVERIFIED`.
3. Keep the item in the supervised hold/manual-review path.
4. Capture logs and release metadata.
5. Restore the last qualified release only after integrity checks.

### ESP32 acknowledgement or reject-cycle failure
1. Do not assume the item was physically rejected because the model returned `FAIL`.
2. Stop/hold the tabletop sequence and inspect the physical state.
3. Reconcile command ID, ACK, completion event, and sensor/operator evidence.
4. Do not blindly replay a non-idempotent action.
5. Resume after the machine state is known and the fault is cleared.

## 15. Implementation phases

### Phase A — Observability foundation
- Add structured inspection events and correlation IDs.
- Persist model/policy release IDs and image hashes.
- Record latency, image validation, runtime errors, and machine-action state.
- Expose local health and readiness endpoints.

### Phase B — Baseline reports
- Export score and latency summaries.
- Capture camera configuration and image-quality measurements.
- Produce a repeatable qualification report with data and label provenance.

### Phase C — Review workflow
- Add review queue and immutable human feedback events.
- Distinguish confirmed labels from inconclusive results.
- Link each review to inspection, artifact, model release, and policy version.

### Phase D — Drift alerts
- Start with transparent, configurable rules and minimum sample counts.
- Add context-aware score/input comparisons.
- Keep alerts advisory unless a validity or safety guardrail requires hold.

### Phase E — Release governance
- Add immutable manifests, regression suite, approval, staged rollout, and rollback.
- Verify candidate release with actuators disabled before any supervised hardware run.

## 16. Acceptance criteria

- [ ] Every inspection references a model release and policy version or records them as unavailable.
- [ ] Invalid or missing input never becomes `PASS`.
- [ ] Score values have documented semantics and are not misrepresented as probabilities.
- [ ] Input, score, quality-label, runtime, and actuator signals are tracked separately.
- [ ] Alert records include metric, baseline, window, sample count, and reason.
- [ ] Operator review preserves the original decision and creates a separate audit event.
- [ ] Candidate model releases are evaluated on a fixed holdout protocol.
- [ ] Threshold changes are versioned, tested, and approved.
- [ ] Model artifacts are immutable and rollback is rehearsed.
- [ ] Duplicate machine commands cannot cause an uncontrolled repeated reject cycle.
- [ ] Monitoring continues to operate locally without cloud access.
- [ ] Retention, backup, restore, and disk-full behavior are tested.
- [ ] Numeric alert thresholds are justified from project data rather than invented defaults.

## 17. Open decisions

Resolve these only after inspecting the actual repository and collecting baseline evidence:
- Product/category and defect taxonomy.
- Available labeled dataset and quality of labels.
- Actual model implementation, score definition, preprocessing, and artifact format.
- Camera source, capture geometry, lighting, and validated image-quality ranges.
- Required latency and throughput targets.
- Data retention and access policy.
- Review roles and approval authority.
- Baseline window, sample-size rationale, and alert thresholds.
- Whether future deployment needs a formal quality-management or regulatory framework.

## 18. Final rule

Monitoring is an evidence and review mechanism, not permission for the system to change its own quality policy. Any material camera, model, preprocessing, threshold, or hardware change requires an explicit record and appropriate requalification before the platform is treated as reliable.
