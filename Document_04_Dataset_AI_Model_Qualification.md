# Document 04 — Dataset & AI Model Qualification
**Project:** Agentic AI Smart Manufacturing Quality Inspection & Automation Platform  
**Document version:** 1.0  
**Date:** 15 October 2026  
**Status:** Engineering qualification plan — not evidence of model performance  
**Owner:** ML / Computer Vision Engineering  
**Related documents:** Document 01 — Project Charter & Execution Roadmap; Document 02 — Hardware Design & Bill of Materials; Document 03 — Repository Audit & Software Architecture; Production-Grade PRD v3.0

---

## 1. Purpose

This document defines how to inspect the existing dataset and model, reproduce the model's behavior, measure performance on held-out examples, choose a defensible decision policy, and approve a versioned release for the tabletop inspection prototype.

The inspected object/product category is **deliberately undecided**. Select it only after the actual training model, dataset, label structure, and license have been inspected. Do not purchase final conveyor dimensions or claim product-specific accuracy before that gate.

### 1.1 Evidence labels

- **Known project direction:** PatchCore-style anomaly detection has been described as the foundation, with a pretrained WideResNet50-2 backbone, `layer2`/`layer3` feature layers, a representative patch memory bank, nearest-neighbor distances, and an anomaly heatmap.
- **To verify in code:** whether the real implementation uses those exact settings; the library and versions; image preprocessing; coreset sampling; distance/scoring implementation; heatmap smoothing; saved artifacts; thresholds; and inference entry point.
- **Proposed qualification rule:** a recommended engineering control, not a claim that the current application already implements it.
- **Release gate:** must pass with recorded evidence before a model/policy combination controls the physical reject mechanism.

## 2. What must be discovered first

Record the following before changing code or training a new model:

| Item | Evidence to collect | Outcome |
|---|---|---|
| Repository identity | Git URL or ZIP, branch/commit, working-tree state | Immutable audit reference |
| Model type | Framework/class, model entry point, weights or memory-bank artifact | Confirmed implementation |
| Backbone/layers | Actual config and runtime report | Confirm or correct PatchCore assumptions |
| Preprocessing | Resize/crop, normalization, color channel order, interpolation, image decode | Versioned preprocessing profile |
| Training data | Root path, file count, category folders, train/eval split, labels and masks | Dataset inventory |
| Score output | Image score, pixel/patch anomaly map, score direction and semantics | Versioned score definition |
| Decision policy | Current thresholds, threshold source, border cases and failure behavior | Policy inventory |
| Runtime | CPU/GPU, RAM/VRAM, inference latency, peak memory, dependencies | Baseline performance |
| Licensing | Dataset/model/backbone license and use restrictions | Approved-use decision |
| Existing results | Evaluation scripts, frozen splits, metrics and logs | Reproducible baseline or explicit gap |

Do not report "verified" based only on a README, screenshot, notebook output, or successful model load. Inspect the actual runtime path and run a repeatable test.

## 3. Qualification strategy

Use five gates, in order:

1. **G0 — Inventory:** identify the actual model, training data, artifacts, dependencies and license.
2. **G1 — Reproducibility:** same frozen input and artifact produce repeatable outputs within the declared tolerance.
3. **G2 — Dataset integrity:** splits are disjoint at the appropriate group level, labels are reviewed, and image quality/coverage are documented.
4. **G3 — Offline qualification:** score the model on held-out data, tune thresholds only on a calibration set, and report failure modes.
5. **G4 — Controlled physical pilot:** run first in shadow/dry-run mode; only enable the servo reject mechanism after decision logic, idempotency, stopping behavior and operator override are tested.

A gate can be marked `PASS`, `FAIL`, `BLOCKED`, or `NOT_RUN`. Never use blank fields to imply success.

## 4. Baseline model to verify

PatchCore is a memory-based anomaly-detection approach: features from defect-free training images are stored in a representative memory bank, and image patches from a query image are compared with that bank. Distances contribute to an image-level anomaly score and a spatial anomaly map. The model is not automatically a calibrated probability of defect.

**Expected baseline to inspect, not assume:**

- Backbone: pretrained `wide_resnet50_2`
- Feature layers: `layer2` and `layer3`
- Normal training samples used to construct a feature memory bank
- Optional coreset/subsampling step to reduce memory/search cost
- Nearest-neighbor or approximate nearest-neighbor distance search
- Patch-level map and image-level score
- Heatmap resizing/smoothing/post-processing
- Deterministic inference mode and pinned preprocessing

These settings align with documented PatchCore examples in Anomalib, but the project implementation must be checked independently. A different valid implementation is acceptable if it is documented, tested, and versioned.

### 4.1 Required runtime contract

Create a single model adapter that accepts a validated image and returns a typed result. Example contract:

```json
{
  "model_id": "patchcore_<category>_<version>",
  "model_digest": "sha256:<digest>",
  "preprocess_version": "preprocess_v1",
  "score_definition": "patchcore_image_score_v1",
  "image_score": 0.0,
  "score_direction": "higher_is_more_anomalous",
  "anomaly_map_available": true,
  "latency_ms": 0,
  "runtime_status": "OK",
  "error_code": null
}
```

The numeric score above is a schema example only; it is not a real result, valid threshold, or calibrated probability. Do not force scores into a 0–1 range unless the actual scoring implementation defines and validates that transformation.

Error cases must return a structured error or raise a typed exception for the orchestrator to convert into `UNVERIFIED`; they must not fabricate a score.

## 5. Dataset selection and product-category decision

Choose one category only after inspecting the assets. The selected category must meet all of these conditions:

- Training examples represent acceptable/normal items under a clearly described process.
- Available examples are relevant to the planned camera geometry, lighting, background, material, scale and surface/shape of the candidate item.
- The intended defect/anomaly behavior can be inspected safely and repeatably on a tabletop.
- At least some independent normal examples and realistic defect/anomaly examples can be reserved for evaluation.
- Use rights and license permit the intended use.
- The object can be transported and consistently positioned on the conveyor and can be safely diverted by a low-force prototype arm.

If the existing dataset belongs to a different object category or image domain, treat it as a software smoke-test dataset only. It must not be represented as evidence of performance on the eventual physical object.

## 6. Dataset partitioning

Create three logical sets and never tune on the final test set.

| Split | Purpose | May contain defects? | Permitted use |
|---|---|---:|---|
| `train_normal` | Build/fill the PatchCore memory bank | Normally no | Fit feature memory only |
| `calibration` | Set score thresholds and policy boundaries | Yes, with labels; should include representative normal cases | Threshold/policy selection |
| `test_locked` | Final unbiased performance report | Yes, with labels | Evaluation only; no threshold changes after inspecting outcomes |

For anomaly detection, the memory bank should be fitted using defect-free training images unless the inspected implementation and approved method explicitly say otherwise.

### 6.1 Leakage prevention rules

- Group related frames, bursts, video clips, duplicate images, repeated captures of the same physical item, production lot, and capture session before splitting.
- Keep near-duplicates and repeated frames from the same event in one split.
- Where multiple product instances or manufacturing lots exist, split by instance/lot/session when possible, not by randomly shuffling individual frames.
- Compute perceptual hashes or equivalent near-duplicate checks where practical; manually review high-similarity matches across splits.
- Freeze a split manifest and hash before the final evaluation.
- Never add test images to the memory bank or use test outcomes to change preprocessing, heatmap processing, thresholds, or category choices.
- If data is too small for a separate calibration and locked test set, document that limitation and use grouped cross-validation or a staged data-collection plan. Do not pretend the resulting estimate is an independent final test.

## 7. Data acquisition protocol

For each capture session record:

- Physical object ID or pseudonymous sample ID; lot/batch when available.
- Normal / known anomaly / unknown label and label source.
- Camera device and phone/app mode; lens/camera selection if relevant.
- Image resolution, orientation, encoding, timestamp and capture session.
- Distance, angle, object pose, field of view and region of interest.
- Lighting setup, exposure, focus, white balance and background.
- Relevant process conditions and any known confounders.
- Image-quality notes: blur, glare, clipped highlights, shadows, occlusion, crop errors and motion.

Use a fixed baseline setup for the first qualification run. After the baseline passes, vary one condition at a time to understand robustness. Save the original image unchanged; derive resized/cropped/normalized inputs reproducibly in preprocessing rather than editing the source files manually.

### 7.1 Recommended capture coverage

Collect independent normal examples across legitimate normal variation, such as item position, orientation, batch/lot, acceptable surface variation and day/session. Anomaly examples should cover realistic suspected defect modes—not just dramatic artificial marks. Where defects cannot be safely or reliably created, record that the defect family is not qualified.

The number of samples must be chosen based on the diversity of the product and the risk of false acceptance. Do not use a universal minimum sample count as a substitute for statistical confidence. Report counts by split, class/defect family, lot/session and acquisition condition.

## 8. Labels and data quality

Use a controlled label vocabulary:

- `NORMAL_CONFIRMED`
- `ANOMALY_CONFIRMED`
- `UNKNOWN_OR_DISPUTED`
- `IMAGE_UNUSABLE`

For anomaly examples, record defect family and severity if known. If pixel masks are available, document who annotated them and the annotation protocol. If masks are unavailable, image-level metrics can still be computed, but claims about pixel-level localization accuracy are limited.

An operator's initial opinion is not automatically ground truth. Prefer review by a qualified person familiar with the product criteria. Track disputed cases separately; do not silently force them into normal/anomalous labels.

### 8.1 Data quality rejection

Image-quality checks must identify, at minimum, corrupted/decode-failed images, insufficient resolution, severe blur, excessive glare, object missing from the region of interest, severe occlusion, unsupported channel/format, and inconsistent orientation. The result should be a reason-coded failure such as `IMAGE_DECODE_FAILED` or `IMAGE_QUALITY_BELOW_MINIMUM`, and the final disposition should be `UNVERIFIED` unless a separately approved policy applies.

## 9. Suggested dataset layout and manifest

Example layout; adapt to the actual dataset without silently copying files into new splits:

```text
data/
  README.md
  manifests/
    dataset_manifest_v1.csv
    split_manifest_v1.csv
    label_review_v1.csv
  train_normal/
    <sample_id>.<ext>
  calibration/
    <sample_id>.<ext>
  test_locked/
    <sample_id>.<ext>
  annotations/
    masks/                 # optional, if pixel masks exist
  reports/
    data_quality_v1.json
```

A manifest should contain at least:

| Field | Meaning |
|---|---|
| `sample_id` | Stable unique ID; never derived solely from row number |
| `relative_path` | Path relative to the declared dataset root |
| `sha256` | Hash of original file bytes |
| `split` | `train_normal`, `calibration` or `test_locked` |
| `label` | Controlled label vocabulary |
| `defect_family` | Known defect family or null |
| `group_id` | Instance/lot/session group used to prevent leakage |
| `capture_session_id` | Acquisition event identifier |
| `camera_profile` | Versioned camera profile |
| `preprocess_profile` | Versioned preprocessing |
| `label_source` | Inspector/reviewer/imported dataset and provenance |
| `mask_path` | Optional reference to a pixel mask |
| `license_source` | Dataset/source plus license identifier |
| `notes` | Non-sensitive caveat/condition notes |

The quality report should list total images, decodes failed, duplicate/near-duplicate candidates, class/split counts, missing fields, corrupt masks, resolution distribution, and any exclusions with reason codes.

## 10. Public benchmarks and usage rights

Public datasets can help reproduce a method or compare a baseline, but they do not replace validation on the physical object's domain.

- **MVTec AD** contains more than 5,000 high-resolution images across 15 object and texture categories, with defect-free training images and test images including defects and normal samples. It also supplies pixel-precise anomaly annotations. Its official page lists the license as **CC BY-NC-SA 4.0** and explicitly says commercial use is not permitted under that license.
- **MVTec AD 2** adds eight challenging scenarios with more than 8,000 high-resolution images, including lighting conditions that may differ from training. Its official page also lists a **CC BY-NC-SA 4.0** license and describes a private test portion evaluated through the official server.

**License gate:** do not use MVTec AD or MVTec AD 2 assets in a commercial release, customer-delivered dataset, or commercial training pipeline unless the applicable rights have been reviewed and the necessary permission obtained. Keep public benchmark data, project-collected data and customer data provenance separate. Also check the licenses of code, pretrained weights, and all transitive components.

## 11. Reproducibility and artifact versioning

Every experiment must have an immutable run record containing:

- `run_id`, timestamp in UTC, Git commit, working-tree status and experiment owner.
- Dataset version, manifest hash, split-manifest hash and exclusion report.
- Model implementation/library versions; Python, PyTorch, torchvision/timm and nearest-neighbor backend versions as applicable.
- Backbone, feature layers, pretrained-weight source/digest, coreset ratio, neighbor count and any other model-specific settings.
- Input color convention, image size, crop, normalization, interpolation and any test-time transformation.
- Memory-bank artifact hash, tensor shape/dtype and build parameters.
- Score definition, map-generation and smoothing settings.
- Calibration policy/thresholds and the exact calibration manifest hash.
- Hardware, OS, CPU/GPU, accelerator and inference configuration.
- Per-image predictions, ground truth, reason codes, runtime and error status.
- Evaluation report and links to the immutable model artifacts.

Do not overwrite an artifact in place. A changed weight file, memory bank, preprocessing operation, score implementation, threshold or decision policy creates a new version or release candidate.

## 12. Evaluation plan

### 12.1 Image-level metrics

Report at least:

- Confusion matrix at the chosen threshold.
- Defect/anomaly recall (sensitivity) and false-accept rate on confirmed anomalous items.
- False-reject rate on confirmed normal items.
- Precision and F1 where class balance and use case make them meaningful.
- AUROC and AUPRC over the continuous image score, when sample counts and labels support them.
- Counts, uncertainty/intervals where appropriate, per-defect-family results and per-condition results.

Always define which class counts as positive and which metric direction is desirable. For quality inspection, false acceptance/defect escape and false rejection often have different costs; report them separately. A high AUROC alone does not choose the right operational threshold.

### 12.2 Localization metrics

If trustworthy pixel masks exist, report image-to-mask alignment and pixel-level metrics such as pixel AUROC/AUPRC, plus a clearly specified overlap metric where useful. Include qualitative heatmap overlays with false positives and false negatives. Do not state that a heatmap accurately outlines a defect merely because it looks plausible.

If there are no pixel masks, describe heatmaps as visual explanation aids and assess them qualitatively; do not report unsupported segmentation metrics.

### 12.3 Runtime and resource metrics

On the target laptop/PC, measure:

- Warm and cold start latency separately.
- Capture-to-result, preprocess, inference, map generation and persistence durations separately.
- p50, p95 and p99 latency after an explicitly stated warm-up and sample count.
- Peak RAM and GPU/VRAM use; CPU/GPU utilization and device temperature if available.
- Memory-bank size and load time.
- Error rate and behavior during repeated inference, missing images, invalid images and model load failures.
- Sustained run stability for a specified number of inspections and duration.

Never compare latency numbers unless the hardware, input dimensions, preprocessing, batch size, and timing boundary are the same or differences are explicitly accounted for.

## 13. Threshold selection and the three-outcome policy

PatchCore scores are implementation-specific distances or score transformations; they are not automatically calibrated probabilities. The numeric threshold must be measured from the exact released artifact and preprocessing path.

### 13.1 Calibration workflow

1. Freeze the training memory bank and its digest.
2. Run the calibration set through the exact release-candidate inference adapter.
3. Plot score distributions for confirmed normal and anomalous examples, including per-defect-family results.
4. Choose candidate thresholds to meet the project's risk priorities; document the false-accept/false-reject trade-off.
5. Define a review band or additional uncertainty rules where the available evidence supports them. Do not invent a confidence margin without validation.
6. Evaluate the selected policy once against `test_locked`.
7. If the policy changes after seeing test results, retire that test as a final holdout and collect a new locked test or document the work as exploratory.
8. Store the threshold and policy version with the model release.

### 13.2 Required outcome semantics

- **PASS:** valid evidence, model and policy ran successfully, score satisfies the approved accept rule, and no mandatory check failed.
- **FAIL:** valid evidence and approved policy satisfy the reject rule.
- **UNVERIFIED:** image quality is insufficient; model/runtime is unavailable; input is out-of-contract; a score lies in an approved review region; required identity/context is missing; or required checks conflict.

For the tabletop prototype, `UNVERIFIED` should illuminate amber and enter a manual review path. It must not be silently converted to PASS. Whether the conveyor resumes, remains stopped, or requires an operator action is a separate versioned machine policy. The first physical prototype is intended to stop during capture/inference and wait for a terminal result or manual `UNVERIFIED` resolution.

### 13.3 Decision-to-actuation separation

Model qualification approves model outputs and a decision-policy candidate; it does not by itself authorize the servo to move. Physical action also requires tested state transitions, duplicate protection, action acknowledgement, actuator limits, stop behavior, and safe recovery. The ESP32 executes only bounded commands; it does not interpret model scores or allow an LLM to control outputs.

## 14. Robustness and failure-mode matrix

| Test condition | What to measure | Expected safe behavior |
|---|---|---|
| New capture session / different lot | Score shift and outcome distribution | Record subgroup; flag material drift for review |
| Allowed pose/position variation | False rejects and missed anomalies | Meets predeclared limits or restrict setup |
| Lighting change / glare / shadow | Scores, quality-check rate and outcome changes | Mark unsupported/poor evidence `UNVERIFIED` rather than silently PASS |
| Blur / motion / focus failure | Detection rate and image-quality response | Reason-coded `UNVERIFIED` |
| Partial occlusion or object outside ROI | Quality checks and heatmap | No automatic PASS when required area is not inspected |
| Background / fixture change | Score shift, false positives | Detect or constrain configuration; document recalibration |
| Corrupt/truncated/unsupported image | Parser/error behavior | Typed error; no score invented |
| Missing model artifact / incompatible version | Startup and inference behavior | Not ready or `UNVERIFIED`; never default PASS |
| Inference timeout / OOM / exception | Deadline handling and trace | Bounded retry then visible exception |
| Threshold boundary | Exact comparator and rounding behavior | Deterministic, unit-tested outcome |
| Duplicate trigger / retry | Decision and actuation count | One logical inspection/action per idempotency key |
| Machine/sensor unavailable | Workflow state | Explicit blocked/error state; no fake acknowledgement |
| Cloud/Wi-Fi unavailable | Local inference and record durability | Prototype continues locally if its local dependencies work; no cloud dependency for decision |
| New category or major camera change | Out-of-domain behavior | Not covered by existing release; requalify before acceptance claims |

## 15. Experiment sequence

### E0 — Inventory the existing model (first)
- Locate entry point, weights, memory bank and inference function.
- Print actual model/backbone/layers/preprocessing/config and all package versions.
- Inventory dataset files, labels, split rules, license and existing results.
- Run one normal and one known anomalous example, if available, and persist all intermediate outputs.

**Exit gate:** the model and data pipeline are unambiguously identified or a blocker report lists the missing artifacts.

### E1 — Reproduce baseline
- Pin dependencies and set deterministic/evaluation mode where supported.
- Re-run a frozen sample list.
- Save input hash, model/artifact hash, score, map, output image and latency.
- Verify that repeated inference is stable within the explicitly declared numeric tolerance.

**Exit gate:** repeatable outputs and complete provenance.

### E2 — Audit dataset
- Build the manifest and hash all source files.
- Validate labels and masks, find corrupt files and near duplicates.
- Group and freeze the splits; record exclusions.
- Review dataset license for intended use.

**Exit gate:** no known leakage across splits; dataset limitations and license are documented.

### E3 — Calibrate and evaluate
- Use calibration data only for thresholds and policy boundaries.
- Evaluate `test_locked` once after the policy is frozen.
- Report error counts, false accept/reject trade-off, per-group coverage, localization (if valid masks exist), latency and resource use.

**Exit gate:** results meet predeclared project/pilot targets or documented blockers prohibit automatic disposition.

### E4 — Live camera shadow mode
- Integrate phone camera by the approved transport.
- Run inference and display results without actuating the reject arm.
- Record misalignment, blur, repeatability, item timing and distribution shift under the tabletop lighting setup.

**Exit gate:** capture/score path stable across repeated sessions; all camera/model errors are visible.

### E5 — Bounded actuation pilot
- Enable only after all safety and duplicate-protection tests pass.
- Use lightweight safe samples and a guarded area; run PASS/FAIL/UNVERIFIED scenarios, timeouts, retries and power/network interruption tests.
- Ensure that reject status is recorded separately from the quality disposition and that an action is not described as successful until observed/acknowledged.

**Exit gate:** signed test record and operator approval for supervised tabletop demonstration.

## 16. Model release checklist

A model/policy release candidate must not be marked approved unless every applicable item is evidenced:

- [ ] Dataset provenance and permitted-use review complete.
- [ ] Dataset manifest, hashes, exclusion reasons and frozen split manifest saved.
- [ ] Model implementation and dependencies identified and pinned.
- [ ] Preprocessing and score semantics versioned.
- [ ] Model/memory-bank artifact is immutable and digested.
- [ ] No train/calibration/test leakage found in audit.
- [ ] Calibration procedure and thresholds documented.
- [ ] Locked-test metrics, confusion matrix and error examples archived.
- [ ] False acceptance and false rejection reviewed against the risk of the selected use case.
- [ ] `UNVERIFIED` behavior exercised for bad images and inference failures.
- [ ] Heatmap behavior inspected; localization claims match evidence.
- [ ] Runtime, peak memory and sustained stability measured on the intended host.
- [ ] Camera-shift / lighting / blur / occlusion robustness tests completed or restrictions explicitly set.
- [ ] Regression set saved to prevent later changes from silently degrading results.
- [ ] Rollback path and release identity verified.
- [ ] Human review and action integration separately approved before actuating the servo.

Release decision: `APPROVED_FOR_SHADOW`, `APPROVED_FOR_SUPERVISED_TABLETOP`, `REJECTED`, or `BLOCKED`. Do not use `PRODUCTION_APPROVED` for the tabletop prototype without a separate production qualification process.

## 17. Deliverables to commit

Expected artifacts, with versions or digests in names/metadata:

```text
ml/
  README.md
  configs/
    model_config.yaml
    preprocess_config.yaml
    decision_policy.yaml
  data/
    manifests/
      dataset_manifest_v1.csv
      split_manifest_v1.csv
  reports/
    dataset_quality_v1.json
    baseline_reproduction_v1.json
    locked_test_report_v1.md
    robustness_report_v1.md
  artifacts/
    model_manifest.json
    memory_bank_manifest.json
  regression/
    regression_cases_v1.csv
```

Large source datasets, customer images and model weights should not be committed to Git unless the repository's privacy, size and licensing rules explicitly allow it. Store large assets in approved storage with hashes and access controls, and commit only manifests/references as appropriate.

## 18. Risk register

| Risk | Impact | Control |
|---|---|---|
| Existing implementation differs from assumptions | Wrong pipeline or false claims | Audit code and artifact metadata first |
| Test leakage / near-duplicates | Optimistic results | Group-based split, hashes, duplicate review |
| Public dataset license incompatible with commercial use | Rights and launch risk | License gate; seek permission or use properly licensed/project-collected data |
| Normal training data contains defects | Memory bank learns defects as normal | Review training samples; sample audit; curate normal-only set |
| Unrealistic lab defects | Hidden production misses | Collect representative defect modes and disclose untested types |
| Threshold picked by visual guesswork | Uncontrolled false acceptance/rejection | Calibration data, locked test, risk-based acceptance |
| Lighting/camera drift | Score distribution changes | Fixed capture design, monitoring and requalification |
| Heatmap visually persuasive but wrong | Operator over-trust | Validate localization if masks exist; train operator on limits |
| Missing score treated as zero or PASS | Unsafe false accept | Typed errors and fail-closed outcome mapping |
| Model changes without traceability | Irreproducible decisions | Immutable release IDs and digest checks |
| CPU latency too high for line | Missed takt / repeated parts | Measure on target host; slow belt; bounded queues and timeout |
| Evidence stored only in dashboard/cloud | Evidence lost during outage | Durable local records and explicit retention policy |

## 19. Decision log / open items

| ID | Question | Default until resolved | Owner / status |
|---|---|---|---|
| D04-01 | Which physical product/category is inspected? | Defer selection until model/data inventory | Open |
| D04-02 | Does the actual implementation use WideResNet50-2 `layer2`/`layer3`? | Treat as expected context, verify in code | Open |
| D04-03 | Which framework/runtime and versions are used? | Inspect lockfiles/environment | Open |
| D04-04 | What dataset and what license? | No commercial use assumed until cleared | Open |
| D04-05 | Are pixel masks available? | Do not claim localization metrics without valid masks | Open |
| D04-06 | What are acceptable false-accept and false-reject rates? | Define after risk/use-case review and sample count | Open |
| D04-07 | What score thresholds are valid? | No thresholds specified in this document | Open |
| D04-08 | What is the hardware latency budget? | Benchmark on laptop/PC before conveyor speed is set | Open |
| D04-09 | What evidence can be retained? | Store only with clear provenance and access/retention rules | Open |

## 20. Immediate working checklist

1. Make a read-only copy/branch of the current repository and record the commit.
2. Locate model loading, inference, preprocessing, heatmap creation, thresholding and label mapping.
3. Locate the actual training data and model artifacts; do not guess from filenames alone.
4. Produce dataset counts, extensions, dimensions, labels and license inventory.
5. Run the existing inference path on a frozen set and save raw score/map outputs.
6. Create the manifest and split audit before retraining.
7. Report blockers and actual results; do not change several variables at once.
8. Only after the baseline is understood, choose the physical inspection category and adjust conveyor/camera geometry.

## 21. References

1. Roth et al., **PatchCore: Towards Total Recall in Industrial Anomaly Detection**, arXiv:2106.08265: https://arxiv.org/abs/2106.08265
2. Anomalib, **PatchCore documentation**: https://anomalib.readthedocs.io/en/stable/markdown/guides/reference/models/image/patchcore.html
3. MVTec, **MVTec AD dataset and license terms**: https://www.mvtec.com/research-teaching/datasets/mvtec-ad
4. MVTec, **MVTec AD 2 dataset and license terms**: https://www.mvtec.com/research-teaching/datasets/mvtec-ad-2

External references explain the method and public dataset conditions. The repository and its files must determine the actual implementation status.
