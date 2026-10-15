# Document 13 — Dataset Governance, Annotation & Model Release Workflow

**Project:** Agentic AI Smart Manufacturing Quality Inspection & Automation Platform  
**Document type:** Data and model lifecycle specification  
**Version:** 1.0  
**Status:** Proposed workflow; current repository and dataset inventory remain unverified  
**Deployment target:** Local-first tabletop prototype using a phone camera, Linux workstation, PatchCore-style anomaly detection, local storage, and ESP32-based supervised actuation.

---

## 1. Purpose

Define a repeatable, auditable process for collecting, labeling, versioning, splitting, qualifying, releasing, and rolling back inspection datasets and model artifacts.

The intent is to ensure that every inspection can be traced to the model release, preprocessing configuration, decision policy, and data protocol that produced it. A model or threshold must not be updated silently, and a test set must not become a tuning set through repeated use.

This is a **proposed engineering specification**, not evidence that the project already has these capabilities. Before implementation, inspect the actual repository, enumerate datasets and licenses, and verify the current model’s true score semantics and preprocessing behavior.

## 2. Core principles

1. **Trace every artifact:** dataset, image, label, split manifest, model artifact, policy, and evaluation report receive stable identifiers.
2. **Preserve source data:** originals are immutable; corrected annotations create new versions and retain history.
3. **Separate data roles:** training/reference data, validation/tuning data, and final test data have distinct roles.
4. **Prevent leakage:** near-duplicate frames, same physical item, capture session, batch, or production run must not be split carelessly across evaluation boundaries.
5. **Do not invent labels:** uncertain or contradictory examples remain explicitly uncertain until adjudicated.
6. **Keep model and policy separate:** weights, preprocessing, and threshold policy are versioned components with compatible release metadata.
7. **Require evidence to promote:** a release needs evaluation, review, regression tests, and a rollback target.
8. **No autonomous production promotion:** agents can summarize evidence or recommend a review, but they cannot approve a model or change thresholds by themselves.
9. **Failure is not good product:** missing, corrupted, out-of-distribution, incompatible, or inconclusive inputs must not be converted to `PASS`.

## 3. Scope and boundaries

### In scope
- Dataset inventory and provenance.
- Image capture protocol and capture metadata.
- Annotation taxonomy, review, adjudication, and corrections.
- Data quality and leakage checks.
- Split manifests and evaluation protocols.
- PatchCore-style normal/reference memory-bank governance where applicable.
- Model, preprocessing, policy, and evaluation manifests.
- Release approval, staged rollout, rollback, and retirement.
- Data retention, licensing, access, and audit trail.

### Out of scope
- Choosing the final product category before the project has inspected available data and the actual model implementation.
- Promising a particular accuracy or defect-detection rate without evidence.
- Automatically retraining or deploying from live operator feedback.
- Treating MVTec AD or any public dataset as automatically suitable, licensed for every use, or representative of the selected real product.
- Treating a successful benchmark run as proof of production readiness.

## 4. Dataset inventory and identity

Every dataset must have a machine-readable inventory record.

### 4.1 Required dataset manifest fields

| Field | Meaning |
|---|---|
| `dataset_id` | Stable identifier, never reused |
| `dataset_version` | Immutable version string or revision |
| `created_at_utc` | Creation timestamp |
| `owner` | Responsible person/team |
| `purpose` | Reference/train, validation, final test, robustness, or demo |
| `product_category` | Exact item family/category; unresolved until selected |
| `source` | Captured internally, public dataset, supplier, customer, or synthetic |
| `source_reference` | URI, archive name, capture session ID, or document reference |
| `license_and_terms` | License name, attribution, usage limits, and review status |
| `capture_protocol_version` | Camera setup and capture procedure revision |
| `annotation_schema_version` | Taxonomy and labeling rules revision |
| `split_manifest_id` | Exact train/validation/test membership record |
| `content_manifest_hash` | Hash of canonical manifest/content inventory |
| `known_limitations` | Missing classes, lighting coverage, uncertain labels, or other gaps |
| `approval_status` | Draft, reviewed, approved-for-use, restricted, or retired |

Dataset identifiers must refer to content snapshots, not a mutable folder whose membership can change without trace.

### 4.2 Per-image metadata

Retain where available:
- stable `image_id`,
- cryptographic content hash,
- source dataset/version,
- capture timestamp and session ID,
- physical item ID or anonymized unit/batch reference,
- camera source/configuration and capture method,
- resolution, exposure/lighting setup, orientation, and preprocessing/crop revision,
- product/category and production context,
- label and annotation version,
- label source and confidence/status,
- split assignment,
- retention classification,
- exclusion reason if not used for model development.

Avoid capturing unnecessary personal or unrelated background data. Store large image bytes as files/artifacts and keep references plus hashes in structured metadata.

## 5. Data intake and provenance

For every new dataset or capture batch:

1. Record who supplied or captured it, when, and for what intended use.
2. Review usage rights and license terms before importing data.
3. Preserve original files unchanged in a read-only source area where feasible.
4. Generate a file inventory with size, extension, decode result, dimensions, and SHA-256 hash.
5. Detect exact duplicates and flag near-duplicates for review.
6. Record corrupt images, unsupported formats, empty files, and outlier dimensions without silently dropping them.
7. Add capture/product metadata where known; use explicit `unknown` values instead of guesswork.
8. Assign the intake batch a stable ID and snapshot it before annotation or transformation.
9. Document exclusions and reasons in a machine-readable report.
10. Approve the batch for a specific purpose; intake approval is not model qualification.

Do not download, combine, or redistribute a dataset until applicable license and usage conditions are understood. Keep license files and source citations with the dataset record.

## 6. Capture protocol and variation coverage

Before collecting a qualification dataset, define a capture protocol for the chosen product and intended inspection point.

Record:
- camera and lens/source,
- mount position, working distance, viewing angle, and field of view,
- resolution and frame/crop selection,
- focus, exposure, white balance, and lighting configuration,
- background and fixture,
- trigger timing and how one physical item maps to one inspection ID,
- permissible variation in item position and orientation,
- environmental conditions relevant to the image,
- known limitations (glare, occlusion, motion blur, transparent/reflective surface, etc.).

### Capture guidance
- Prefer a stable fixture and repeatable lighting for the first qualification baseline.
- Capture realistic allowed variation, not just nearly identical ideal frames.
- Include representative nuisance conditions separately and label them.
- Do not intentionally mix incompatible camera resolutions or preprocessing versions without recording them.
- For conveyor capture, ensure each frame is linked to the correct physical item/cycle; test stale-frame and adjacent-item mix-ups.
- Save enough context to reproduce the image pipeline without collecting unrelated information.

A camera setup change is a data-domain change. Record it and review whether requalification is required.

## 7. Annotation schema and label governance

The exact defect taxonomy depends on the chosen product and must not be invented before product/model inspection.

### 7.1 General label states
Use explicit states such as:
- `CONFIRMED_GOOD`
- `CONFIRMED_DEFECT`
- `DEFECT_TYPE:<controlled_label>`
- `INCONCLUSIVE`
- `UNLABELLED`
- `EXCLUDED_WITH_REASON`

These are proposed schema examples. Final names should be settled in the annotation-schema version and used consistently.

### 7.2 Annotation requirements
Each annotation should record:
- image ID and content hash,
- label/schema version,
- label value,
- annotator/reviewer identifier or controlled role,
- annotation timestamp,
- evidence or reason,
- confidence/status where allowed by the schema,
- adjudication outcome if reviewers disagreed,
- superseded annotation ID when corrected.

Do not overwrite a prior label without retaining history. Do not treat the model prediction as the source of truth for a label used to evaluate that same model.

### 7.3 Reviewer workflow
1. Apply documented labeling instructions.
2. Flag ambiguous, low-quality, occluded, or borderline examples as `INCONCLUSIVE`.
3. Route disagreements to an independent reviewer or adjudicator.
4. Record the final label and decision rationale.
5. Keep the original annotation and link the corrected version.
6. Exclude unresolved cases from metrics that require definitive labels, but report the exclusion count and reason.
7. Periodically audit a sample of labels for consistency.

### 7.4 Label quality metrics
Track:
- label coverage,
- unresolved/inconclusive rate,
- disagreement rate,
- correction rate after review,
- counts per defect class and source,
- label provenance (single annotator, dual annotation, adjudicated, supplier-provided).

Do not claim reliable inter-annotator agreement unless the design and calculation are appropriate for the label type and sample.

## 8. Data quality controls

Every dataset snapshot should be checked for:
- decode errors and corrupt files,
- duplicate hashes,
- likely near-duplicate frames,
- inconsistent dimensions, color modes, or orientation,
- unexpected blank/black/overexposed images,
- blur or focus anomalies,
- invalid or missing metadata,
- label values outside the schema,
- impossible combinations of product type, defect label, and split,
- image/label association errors,
- class imbalance and underrepresented contexts,
- license/provenance gaps,
- accidental background/person information,
- leakage across splits.

Generate a report with total files, accepted files, quarantined files, exclusions by reason, duplicate candidates, and unresolved metadata. Any exclusion must be explainable and reproducible.

## 9. Split strategy and data leakage prevention

### 9.1 Distinct roles
- **Reference/training set:** used to fit model-specific reference statistics or PatchCore memory bank, and to develop the pipeline.
- **Validation/tuning set:** used to select preprocessing, thresholds, and candidate settings under a documented protocol.
- **Final test set:** held back for final evaluation. Do not repeatedly use it to tune the model or threshold.
- **Robustness/challenge set:** separate set of nuisance conditions and edge cases; report separately from the primary benchmark.

For PatchCore-style anomaly detection, the normal/reference data used to build the memory bank must be tracked as part of the model artifact lineage. Any data used to choose the threshold belongs to the development/tuning process, not to the untouched final test.

### 9.2 Split by independent units
Do not randomly split near-identical video frames from the same item or capture burst across train and test. Group by the most relevant independent unit, which may include:
- physical product/item,
- production lot or batch,
- capture session/day,
- camera setup,
- supplier/source,
- production run.

Choose grouping based on the intended generalization claim. If the evaluation aims to test unseen items under the same setup, hold out physical items. If it aims to test a new session or camera configuration, hold out the relevant session/configuration.

### 9.3 Split manifest
Store the exact image IDs and hashes assigned to each split, the grouping rule, random seed where applicable, creation tool/version, date, and rationale. Once used for a release, the manifest is immutable.

### 9.4 Leakage checks
- Verify exact hashes do not cross splits.
- Run perceptual/near-duplicate checks and review flagged pairs.
- Check physical item/session/batch grouping rules.
- Check that derived crops, augmentations, heatmaps, or cached embeddings do not leak across partitions.
- Ensure threshold tuning did not use the final test results.
- Verify repeated data imports have not changed membership silently.

## 10. Model-specific governance for PatchCore-style anomaly detection

The project context references PatchCore with a WideResNet50-2 backbone, layer2/layer3 features, a memory bank, nearest-neighbor patch distances, and anomaly heatmaps. These are **configuration items to verify against the actual implementation**, not confirmed facts about the current repository.

For each candidate release, record:
- architecture and backbone,
- feature layers and feature embedding details,
- library/runtime version,
- normalization and resize/crop preprocessing,
- memory-bank construction protocol,
- memory-bank sampling/reduction strategy and parameters,
- reference dataset ID/version and exact split manifest,
- artifact and feature-cache hashes,
- raw image-level and pixel/patch-level score definitions, if both exist,
- post-processing, smoothing, and heatmap resizing,
- inference device/backend and precision,
- known performance and memory/latency constraints.

For anomaly detection without a conventional supervised class-probability output:
- do not call the anomaly score a probability without calibration evidence;
- define whether larger scores indicate greater anomaly and test that definition;
- state how image-level decisions are derived from patch/heatmap outputs;
- qualify threshold values against a known validation protocol;
- evaluate at the real camera resolution and preprocessing path;
- distinguish image-level detection performance from pixel-level localization quality.

## 11. Evaluation protocol

An evaluation report must identify the exact model release candidate, dataset snapshot, split manifest, policy version, and code revision.

### 11.1 Required reporting
Where appropriate to the task and labels, report:
- sample counts by split and confirmed label,
- AUROC and/or average precision with definition and averaging method,
- precision, recall, false-accept rate, and false-reject rate at the selected threshold,
- confusion matrix and denominators,
- per-defect or per-context breakdown,
- localization metrics only if pixel-level ground truth exists and the metric is suitable,
- uncertainty/inconclusive/excluded counts,
- latency p50/p95/p99 and resource usage,
- robustness results for camera/lighting/position/blur and other known nuisances,
- results for failed, stale, or unsupported input paths,
- known limitations and confidence/uncertainty of conclusions.

No single metric is sufficient. A threshold should be selected based on the costs of false acceptance and false rejection and the intended use, then recorded and approved.

### 11.2 No unsupported claims
Do not state “production accuracy,” “zero false negatives,” or “industry-grade” based only on a small demo set, static public benchmark, or handpicked sample. Separate:
- development benchmark results,
- controlled tabletop evaluation,
- prospective pilot results,
- externally validated/production results (only if actually obtained).

### 11.3 Reproducibility
Retain:
- evaluation command/config,
- environment and dependency lockfile,
- random seeds where relevant,
- dataset/split manifest IDs,
- output metrics and plots,
- logs and artifact hashes,
- evaluator and approval timestamp.

## 12. Release manifest and model registry

Each candidate and released model needs an immutable manifest.

### Required release manifest
- `model_release_id`
- `created_at_utc`
- source code revision/commit if available
- architecture and runtime versions
- model artifact hash(s)
- preprocessing/capture contract version
- reference/training dataset IDs and split manifest ID
- validation and final-test dataset IDs/split IDs
- evaluation report ID/hash
- threshold-policy version (reference only; stored/versioned separately)
- known limitations
- release status: candidate, qualified, active, rolled-back, retired
- approver and approval timestamp
- compatible API/schema/firmware versions if relevant
- rollback target
- artifact storage reference and retention rule

A release must never be overwritten in place. If any content changes, create a new release ID and manifest.

## 13. Promotion gates

| Gate | Required evidence | Pass condition |
|---|---|---|
| G0 — Provenance | Dataset manifests and usage-rights review | Source and allowed purpose are documented |
| G1 — Data quality | Ingest checks, duplicates, exclusions, label review | No unresolved blocking data-integrity issue |
| G2 — Split integrity | Immutable split manifest and leakage report | No unexplained duplicate/group leakage |
| G3 — Reproducible build | Locked environment and artifact hashes | Candidate can be loaded and identified reproducibly |
| G4 — Evaluation | Final report, metrics, subgroup breakdown, limitations | Meets pre-agreed acceptance criteria |
| G5 — Runtime and integration | API, camera, policy, persistence, and error-path tests | Invalid inputs fail closed; records remain traceable |
| G6 — Shadow / supervised pilot | Candidate comparison, operator review, no uncontrolled actuation | Candidate behavior is understood and evidence recorded |
| G7 — Approval | Reviewer sign-off, release manifest, rollback plan | Authorized owner approves explicit release promotion |
| G8 — Post-release review | Monitoring window and issue log | No blocking regression; ongoing monitoring assigned |

Numeric performance criteria must be set based on product risk, dataset quality, and intended use. This document deliberately does not invent accuracy or false-accept thresholds.

## 14. Threshold and policy versioning

Thresholds belong to a decision-policy release, separate from model weights.

Every policy version should define:
- compatible model release(s),
- score field and exact semantics,
- threshold value(s) and units,
- comparison operators and boundary behavior,
- review/uncertainty band if used,
- input-quality gates,
- behavior for missing/invalid score or incompatible model,
- effective date and approval record,
- validation report and rollback target.

Never change thresholds directly in a live config without a new version and review. Do not optimize a threshold repeatedly against the held-out final test. The decision result remains `PASS`, `FAIL`, or `UNVERIFIED`; an LLM must not override this deterministic policy.

## 15. Operator feedback and continuous learning

Live operator labels can be valuable but require governance:
1. Record the original model result and its versions.
2. Collect reviewer label and evidence separately.
3. Mark uncertain labels explicitly.
4. Do not immediately add feedback examples to the training/reference set.
5. Periodically adjudicate and review label quality.
6. Create a new dataset snapshot with provenance and split decisions.
7. Rebuild/evaluate a candidate in a separate workflow.
8. Compare against the current qualified release using the same evaluation protocol.
9. Approve or reject via release gates.

Avoid feedback loops where the model’s prior predictions determine labels that are then used to “prove” the same model performs well.

## 16. Retirement, rollback, and incident handling

### Rollback triggers
Examples:
- confirmed material increase in false acceptance or false rejection,
- model artifact mismatch or corruption,
- image preprocessing changed unexpectedly,
- API/runtime incompatibility,
- unacceptable latency/resource behavior,
- unresolved data leakage discovered in the qualification set,
- release lacks required approval or manifests,
- camera configuration moved outside qualified conditions.

### Rollback procedure
1. Put the line/prototype into supervised hold and use `UNVERIFIED` where appropriate.
2. Preserve affected inspection IDs, images/hashes, policy versions, and command records.
3. Disable promotion of the suspect candidate.
4. Restore the last known qualified model and compatible policy using the documented manifest.
5. Verify artifact hashes, model readiness, input pipeline, database, and actuator state.
6. Run a short acceptance/regression set with actuators disabled.
7. Resume only after the authorized owner records approval.
8. Create an incident record with cause, affected period, impact, and corrective action.

Rollback must never imply that an item already physically handled by the previous release has been retrospectively corrected. Historical records remain immutable; corrections are linked events.

## 17. Storage, licensing, retention, and privacy

- Keep dataset originals read-only where feasible and derived artifacts in separate versioned locations.
- Retain license, attribution, source URL/reference, and redistribution restrictions.
- Avoid placing credentials or sensitive environment details in manifests.
- Restrict access to images, labels, datasets, exports, and release artifacts.
- Define retention and deletion rules before collecting large volumes of real inspection data.
- Keep backup/restore procedures and verify that hashes still match after restore.
- Ensure deletion does not silently leave invalid references or erase only copies of evidence needed for unresolved incidents.
- Use synthetic/redacted examples for public bug reports where possible.
- If cloud storage or dataset sync is added, assess access control, region, retention, and offline behavior separately.

## 18. Roles and responsibilities

| Role | Responsibilities | Cannot do alone |
|---|---|---|
| Data owner | Approves sources, purposes, retention, and dataset snapshots | Declare model qualified without evaluation |
| Annotator | Applies current label schema and records uncertainty | Rewrite history or approve own disputed labels |
| Adjudicator/reviewer | Resolves label disagreements and reviews evidence | Silently change model threshold |
| Model developer | Builds candidates and evaluation reports | Promote own candidate without required approval |
| Release approver | Reviews gates, limitations, and rollback plan | Skip required evidence without documented exception |
| Operator | Runs supervised inspections and raises concerns | Change model artifacts or policy outside approved flow |
| Agent/LLM | Summarizes telemetry or proposes a review | Label ground truth autonomously, approve releases, or control actuators |

For a solo prototype, one person may temporarily cover multiple roles, but approval records should still state which review steps were performed and which independent checks are unavailable.

## 19. Implementation roadmap

### Phase A — Inventory before changing code
- Locate the actual model, preprocessing, dataset loaders, evaluation scripts, and artifact outputs.
- Record current behavior and gaps without refactoring first.
- Identify existing manifests, configuration, and licensing records.

### Phase B — Data manifests and validation
- Add dataset/image manifests and file hashes.
- Add decode, duplicate, metadata, schema, and leakage checks.
- Add quarantine/exclusion reports.

### Phase C — Annotation and split governance
- Define product-specific taxonomy after product selection.
- Add annotation versioning, review state, adjudication, and immutable split manifests.
- Verify grouped splitting and near-duplicate detection.

### Phase D — Reproducible evaluation and releases
- Add locked environment and evaluation configuration.
- Generate evaluation reports linked to exact data/model/policy versions.
- Add release manifests, approval states, and rollback pointers.

### Phase E — Operations and monitoring
- Integrate release IDs and policy versions into inspection records.
- Monitor current release and input conditions.
- Rehearse rollback with actuators disabled before supervised hardware testing.

## 20. Acceptance checklist

- [ ] Every dataset snapshot has a stable ID, version, owner, source, purpose, and license status.
- [ ] Image hashes and provenance are stored and verified.
- [ ] Originals are preserved; corrected labels are versioned rather than overwritten.
- [ ] Uncertain cases remain explicit and are not silently treated as good.
- [ ] Splits are immutable and grouped to prevent item/session leakage.
- [ ] Exact duplicates and near-duplicate candidates are checked across splits.
- [ ] PatchCore memory-bank/reference data lineage is recorded if PatchCore is confirmed in the implementation.
- [ ] Model and policy releases are separate, immutable, and traceable.
- [ ] Evaluation reports identify data, splits, code, model, preprocessing, and policy.
- [ ] Thresholds are selected using a documented development protocol, not repeated final-test tuning.
- [ ] Numeric release criteria are explicitly agreed before qualification.
- [ ] A rollback target exists and rollback is tested.
- [ ] Operator feedback is not used as ground truth without review.
- [ ] Licensing, retention, privacy, backup, and access controls are documented.
- [ ] No agent can autonomously promote a model or change decision thresholds.
- [ ] Invalid or incompatible data/model state returns `UNVERIFIED` or hold behavior, never implicit `PASS`.

## 21. Open decisions

Resolve after repository and dataset inspection:
- Selected product category and defect taxonomy.
- Exact current model implementation, anomaly-score definition, and preprocessing.
- Dataset availability, provenance, usage rights, and label quality.
- Intended use of the detector and relative costs of false accepts/rejects.
- Capture setup and expected operating variation.
- Grouping unit for independent splits (item, batch, session, or production run).
- Metrics and numeric release thresholds appropriate to the intended claim.
- Annotation/review ownership and feasible independent review.
- Data retention, privacy, and backup requirements.
- Model registry/storage mechanism and artifact signing/integrity approach.

## 22. Final rule

A model is not qualified because it runs, produces a heatmap, or performs well on a small demonstration set. Qualification requires traceable data, leakage-resistant evaluation, explicit policy versions, evidence-based approval, and a tested rollback path. If the model, data, input conditions, or decision policy cannot be verified, the inspection flow must fail safely to `UNVERIFIED`/hold rather than claim a pass.
