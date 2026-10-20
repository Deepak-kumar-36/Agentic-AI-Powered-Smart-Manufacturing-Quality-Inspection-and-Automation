# Smart Manufacturing Quality Inspection

Local-first foundation for a traceable manufacturing visual-inspection platform.

## Current evidence boundary

The workspace initially contained engineering specifications but no application or firmware repository, model artifact, dataset, camera, or ESP32 hardware. The current implementation contains a dependency-free deterministic decision policy, a dependency-lazy native EfficientAD-S checkpoint adapter, a hardware-neutral V4L2 frame adapter, and a dependency-free browser dashboard. It does **not** claim live camera qualification, firmware behavior, hardware verification, or production readiness.

`PASS`, `FAIL`, and `UNVERIFIED` are explicit. Invalid/stale input, unavailable models, invalid scores, and incompatible model releases fail closed to `UNVERIFIED`.

## Runtime

- Python 3.12.x, pinned by `.python-version` and `pyproject.toml`.
- NumPy is pinned in `pyproject.toml` and `requirements.lock` for PatchCore's
  numerical core.
- Torch/torchvision/scipy remain optional until the workstation runtime and
  explicit weight-acquisition procedure are verified. Pillow is pinned because
  the phone MJPEG adapter decodes JPEG frames locally.

## Setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --requirement requirements.lock
```

Install only into `.venv`; no global installation is required. Torch/torchvision/Pillow/scipy are intentionally not in the lockfile until the workstation-compatible ML stack and weight acquisition are verified.

## Test

```bash
make test
```

The test command is offline and exercises policy threshold boundaries, invalid/stale evidence, unavailable and incompatible models, non-finite scores, and invalid policy configuration.

Dashboard histogram regression tests use dependency-free Node.js built-in tests
(optional Node.js 22.20.0 pinned in `.nvmrc`):

```bash
node --test tests/dashboard_analytics.test.cjs
```

`make test` also runs these tests when `node` is present; otherwise it reports
an explicit skip (including in the Python-only Docker image). Anomaly scores
are not probabilities: the dashboard uses ten bins from zero to the observed
nonnegative maximum (at least one), excluding missing, non-numeric, negative,
and non-finite scores.

## PatchCore dataset inventory

The MVTec AD loader never downloads or fabricates data. After obtaining the
dataset through the official publisher's authorized process, run:

```bash
python -m app.patchcore.cli inventory --root /path/to/mvtec_ad
```

The command returns a non-zero status when the root, category layout, image
files, duplicate hashes, or anomaly masks are invalid or incomplete. The
dataset's CC BY-NC-SA 4.0 terms must be reviewed before any use beyond
permitted development/benchmark work.

### Real capsule ingestion and validation

Captured capsule data can be discovered without copying, downloading, or
inventing files. The category root (or a parent containing `capsule/`) follows:

```text
capsule/
  train/good/*.png
  validation/good/*.png
  validation/defects/<defect_type>/*.{png,jpg,...}
  test/good/*.png
  test/defects/<defect_type>/*.{png,jpg,...}
```

Run the reusable discovery path with:

```bash
python -c 'from app.efficientad.data import discover_real_capsule_manifest; discover_real_capsule_manifest("/path/to/capsule").write("/path/to/manifest.json")'
```

Each row contains `identifier`, `path`, `category`, `label`, `defect_type`,
`physical_sample_id`, `capture_session`, `camera_id`, `width`, `height`,
`split`, `mask_path`, and `sha256`. Optional `metadata.json` (or a configured
CSV filename) is keyed by relative `path` or `identifier` and enriches the
physical-sample, session, camera, label, defect, and mask fields. A metadata
row with a null label remains invalid; labels are only inferred from the
directory convention when metadata does not override them.

`validate_manifest(manifest)` reports decode failures, missing/invalid labels,
duplicate content hashes, and physical-sample or capture-session leakage across
splits. Discovery fails closed when any of these checks fail. Masks are
optional by default; pass `CapsuleDiscoveryConfig(require_masks=True)` when the
capture protocol requires defect masks. No images are included in this
repository.

### Real-capsule adaptation and calibration on Kaggle

No real-capsule photographs are present in this repository, so no adaptation
run or improvement claim has been made. Keep product images in a private/local
Kaggle Dataset and do not add them to Git. Before upload, obtain approval for
the intended use, record retention/access restrictions, and assign stable
physical-sample and capture-session identifiers. Avoid putting the same sample
or session in more than one split.

The adaptation notebook is `notebooks/efficientad_s_kaggle.ipynb`. In Kaggle:

1. Attach the private real-capsule Dataset and set `REAL_CAPSULE_ROOT` to its
   mount path (default: `/kaggle/input/real-capsules`).
2. Run the manifest validation cell and stop on any decode, duplicate, label,
   or split-leakage issue.
3. Run the adaptation cell. It trains only from `train/good` and writes a new
   `efficientad-s-native-real-capsule-v1` candidate under
   `/kaggle/working/efficientad_s_real_capsule_v1`.
4. Score the same validation and locked test manifest with both the existing
   MVTec release and the candidate, producing `baseline_scores.csv` and
   `adapted_scores.csv` with `sample_id,score` plus optional latency/model-size
   columns.
5. Run the comparison cell. It calibrates from validation only and reports
   test AUROC/precision/recall/false-rejection/missed-defect metrics. It does
   not qualify or activate the candidate.

Only after human review of untouched test evidence, model hashes,
preprocessing, threshold costs, and licensing may a new release metadata file
be marked qualified. The release loader supports a new `model_version`,
`variant`, and safe `checkpoint_subdir`, while the existing MVTec release
remains available for rollback. Pixel-level metrics remain unavailable when
the private dataset has no verified defect masks; masks are never invented.

## Docker

```bash
docker build -t manufacturing-inspection:test .
docker run --rm manufacturing-inspection:test
```

The image currently runs the offline test suite. It does not enable hardware or download model weights.

## Local API

Start the dependency-free local API with:

```bash
python -c 'from app.api import serve; serve()'
```

It binds to `127.0.0.1` by default and exposes liveness/readiness, system
status, inspection creation, bounded history, inspection retrieval, and event
timeline endpoints. Inspection creation requires an `Idempotency-Key` header.
Without an explicitly injected model and category policy, every submitted
inspection is durably recorded as `UNVERIFIED` with `MODEL_NOT_READY`;
client-supplied scores and outcomes are not trusted. Model-backed requests use
an `image_path` relative to the configured image root and are evaluated by the
server-side policy.

The native EfficientAD-S adapter is available for explicit, verified artifacts:

```python
from app.efficientad.runtime import NativeEfficientADRuntime

runtime = NativeEfficientADRuntime(
    {"bottle": "/path/to/efficientad_s_bottle.pt"},
    "/path/to/teacher_small.pth",
    device="cuda",
)
evidence = runtime.score("bottle", "/path/to/image.png")
print(evidence.score, evidence.model_version)
```

It never downloads weights, requires a category-specific native checkpoint, and
rejects missing files, category mismatches, unsupported variants, missing
checkpoint fields, and teacher-hash mismatches before returning evidence. The
HTTP API is wired to these artifacts only through the reviewed-release assembly
point below; unqualified or incomplete artifacts cannot start a model-backed API.

After review, `app.efficientad.release.load_reviewed_release` is the guarded
assembly point for local use. It requires a full run whose metadata explicitly
contains `qualification_status: QUALIFIED`, verifies the teacher and category
checkpoint hashes, and requires reviewer-supplied thresholds for every category.
Smoke or unqualified runs cannot create a model-backed API.

The reproducible server entry point is:

```bash
python -m app.serve \
  --metadata /path/to/run_metadata.json \
  --artifacts /path/to/efficientad_s_artifacts \
  --teacher /path/to/teacher_small.pth \
  --image-root /path/to/images \
  --db data/inspection.sqlite3 \
  --threshold bottle:0.2:0.8 \
  --threshold screw:0.2:0.8 \
  --threshold capsule:0.2:0.8 \
  --device cuda
```

The example thresholds are placeholders and must not be used without review.
The CLI uses `data/inspection.sqlite3` by default so inspections and event
history survive API restarts. The `data/` directory is intentionally ignored by
Git.

Check the service after startup:

```bash
curl http://127.0.0.1:8000/health/live
curl http://127.0.0.1:8000/health/ready
```

## Browser dashboard

`dashboard/index.html` is a dependency-free browser dashboard for the existing
HTTP API. It keeps the light industrial layout and presents the operator flow,
latest decision, runtime/model metadata, health, analytics, and bounded history
as one vertically scrollable workspace. The sidebar has one primary destination:

- `#dashboard` — the complete operator workspace. Inspection, history, model,
  dataset/training, health, and settings data remain available in context rather
  than as separate navigation pages. The URL `?api=...` still selects the API
  origin; no fabricated dataset, training, or readiness values are shown.

The SPA submits inspections through the existing JSON contract, shows
outcomes/reason codes and scores, lists stored inspection history, and loads
the selected inspection's event timeline. Charts are derived only from records
returned by the API. Values that the API does not return (such as processing
duration or an input-image URL) remain explicitly unknown rather than being
estimated. If an API response includes supported evidence fields
(`evidence.heatmap_url`, `evidence.overlay_url`, `heatmap_url`, or
`evidence_url`), it displays those images; otherwise the dashboard explains
that evidence is unavailable.

The file chooser uploads the selected image to the configured local image root
through `POST /api/v1/images`, then fills the returned safe relative path into
the inspection form. The upload is local-only and rejects corrupt image data.

### Human review and annotation

Selecting an inspection opens an additive Human Review form. Reviewers can record
`CONFIRMED_NORMAL`, `CONFIRMED_DEFECT`, or `INCONCLUSIVE`, with an optional
controlled defect type (`scratch`, `dent`, `crack`, `contamination`,
`misalignment`, or `other`) and a note up to 2,000 characters. Reviews never
modify the original AI outcome, score, model version, policy, or evidence.

The API stores every review and its audit event through:

- `POST /api/v1/inspections/<inspection_id>/reviews`
- `GET /api/v1/inspections/<inspection_id>/reviews`

Review records retain server timestamps, the inspection's model version, and an
available input-image hash. Reviewer authentication is not implemented in this
local prototype, so the UI does not claim verified reviewer identity. Reviews
are preserved separately from dataset manifests and are not automatically
approved as training data.

The dashboard's Review Analytics section uses the latest review per inspection
for operational status while preserving the full history. Coverage is reviewed
inspections divided by total inspections. Agreement and disagreement are counted
only for PASS/FAIL inspections with CONFIRMED_NORMAL/CONFIRMED_DEFECT latest
reviews; INCONCLUSIVE and UNVERIFIED records are excluded from that denominator.
Historical outcome conflicts are counted separately, and the attention queue
includes unreviewed, inconclusive, conflicting, and UNVERIFIED inspections.
These are descriptive AI–human agreement metrics, not production accuracy or
proof of model quality; reviewer selection, label errors, dataset composition,
and missing ground truth can affect them.

### Human-reviewed evidence export

The Review Analytics section can preview and download a bounded ZIP of candidate
evidence through:

- `GET /api/v1/review-export/preview`
- `GET /api/v1/review-export/download`

Exports are limited to 100 records and 64 MiB by default. Optional
`review_outcome`, `ai_outcome`, `limit`, and `byte_limit` query parameters are
validated server-side. The package contains `images/`, `manifest.jsonl`,
`exclusions.csv`, and `README.md`. Images must be readable, hash-verifiable,
definitively reviewed, and free of conflicting human outcomes. Exclusions are
reported with machine-readable reasons; duplicate image hashes are excluded.

The manifest label is derived only from the eligible human outcome
(`normal`/`defect`). The original AI decision, score, model version, timestamps,
and hash provenance remain available for later evaluation. Notes, reviewer
identity, phone URLs, credentials, and internal paths are not exported. The
package does not assign dataset splits, authorize training, alter inspections,
or qualify a model release. Human review identity is not independently
verified and the package is only candidate evidence.

Run the API and static dashboard in separate terminals:

```bash
# Terminal 1: API (use the reproducible app.serve command above when model-backed)
python -c 'from app.api import serve; serve()'

# Terminal 2: static browser server
python -m http.server 4173 --directory dashboard
```

Open <http://127.0.0.1:4173/>. To use another API origin, open
`http://127.0.0.1:4173/?api=http://127.0.0.1:8000` (the default is already
`http://127.0.0.1:8000`). The API includes local-development CORS headers and
supports the browser's `OPTIONS` preflight.

### Dashboard smoke test

With both servers running, verify that the page shows **Online**, that the
**Refresh data** button loads the recent-inspection table and derived charts,
and that submitting a relative path creates a record or shows the API's clear
error. Click a history row and verify that its decision, evidence (when
returned), and event timeline load. If the API has no configured model, the
expected decision is `UNVERIFIED` with `MODEL_NOT_READY`. The dashboard should
also remain usable at approximately 390px and 1024px viewport widths without
horizontal overflow; processing time should remain **Unknown** because it is
not part of the current API response.

Submit a server-scored inspection using an image below `--image-root`:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/inspections \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: local-smoke-001' \
  -d '{"category":"bottle","image_path":"sample.png"}'
```

The client must not send `score` or `outcome`; those fields are ignored and the
decision is produced only from the configured server-side model and policy.

### Offline stored-image workflow

The software-only end-to-end path can capture a checked-in image fixture through
the same `CameraFrame` contract used by hardware sources, save a normalized PNG
under the configured image root, and submit it through the API/policy/store path:

```python
from app.api import InspectionApi
from app.offline_workflow import FileFrameSource, OfflineInspectionWorkflow

workflow = OfflineInspectionWorkflow(
    InspectionApi(store, model=model, policies=policies, image_root="data/captures"),
    FileFrameSource("tests/fixtures/inspection/normal.ppm"),
    "bottle",
    "data/captures",
)
record = workflow.run("offline-smoke-001")
```

This path is covered offline by stored normal, anomalous, and corrupt image
fixtures, plus missing-model, unsupported-category, and SQLite restart cases.
It does not claim EfficientAD inference when optional ML dependencies or reviewed
artifacts are unavailable.

### Camera adapter smoke test

Linux V4L2 sources can be read through the hardware-neutral camera contract without adding OpenCV to the project dependencies:

```python
from datetime import datetime, timezone

from app.camera import FramePolicy, FreshFrameSelector, V4L2CameraSource

source = V4L2CameraSource("/dev/video0", width=640, height=480, fps=30)
selector = FreshFrameSelector(FramePolicy(max_age_ms=1000))
try:
    frame = source.read(timeout_ms=3000)
    if frame is None:
        raise RuntimeError(source.health())
    accepted = selector.accept(frame, now=datetime.now(timezone.utc))
    print(accepted.frame.shape, accepted.sequence_no)
finally:
    source.close()
```

The adapter uses the system `ffmpeg` executable and emits RGB `uint8` frames with camera identity, UTC capture timestamp, dimensions, and monotonic sequence numbers. A successful read does not qualify the camera for actuation; run the camera acceptance matrix in `Document_05_Phone_Camera_Laptop_Setup.md` first.

### Phone camera setup

For a low-cost camera, use an Android camera app that exposes a local MJPEG
endpoint (for example, an IP-camera/MJPEG mode). Connect the phone and laptop to
the same trusted local network, keep the URL runtime-only, and smoke-test it:

```bash
python -m app.phone_camera_smoke \
  --url 'http://PHONE_IP:8080/video' \
  --output data/phone-camera-frame.ppm
```

Replace `PHONE_IP` with the address shown by the phone app. Do not commit the
address, stream URL, credentials, or tokens. The command writes a local PPM
frame, validates freshness and sequence identity, and reports the stream health.
The phone adapter is transport-ready and the consolidated dashboard exposes the
same supervised one-shot flow through `/api/v1/camera/configure`,
`/api/v1/camera/status`, and `/api/v1/camera/capture-inspection`. Camera setup
remains in memory; URLs must resolve to a local/private host and may not contain
credentials or credential-like query parameters. Capture failures produce a
persisted `UNVERIFIED` record when capture was requested, never a client-chosen
decision. The returned record includes the server decision, score, model version,
event timeline, and available heatmap/input evidence. No continuous capture or
actuation is implemented.

### Phone-camera shadow inference

After the phone stream smoke test succeeds, run one or more supervised,
read-only model-backed captures:

```bash
.venv/bin/python -m app.phone_shadow \
  --url 'http://PHONE_IP:8080/video' \
  --category bottle \
  --metadata artifacts/efficientad_s_release/run_metadata.json \
  --artifacts artifacts/efficientad_s_release \
  --teacher models/efficientad/teacher_small.pth \
  --image-root data/phone-shadow \
  --db data/inspection.sqlite3 \
  --threshold bottle:0.1209134872:0.5 \
  --threshold screw:0.2644167006:0.5 \
  --threshold capsule:0.1169489183:0.5 \
  --device cpu \
  --count 1
```

This captures a fresh phone frame, validates it, saves it under the configured
image root, invokes the existing server-side model and policy, and persists the
inspection plus event history. It has no controller or actuation path. Use
`--count` and `--interval-ms` for a bounded supervised run. If the phone is
offline or the stream fails, the command reports `UNVERIFIED` and does not
create a false inspection decision.

When replacing a reviewed checkpoint, replace it atomically and invalidate the
resident cache before serving new requests:

```python
api.reload_model("bottle")  # or api.reload_model() for every category
```

The next request reloads the category and rechecks checkpoint metadata and the
reference teacher hash. Cache invalidation is intentionally an in-process
operation; it is not exposed as an unauthenticated HTTP endpoint.

## Kaggle EfficientAD-S experiments

The Kaggle entry point is `notebooks/efficientad_s_kaggle.ipynb`. It expects
the authorized MVTec AD dataset attached at
`/kaggle/input/datasets/ipythonx/mvtec-ad`, validates the MVTec layout, and starts with
`bottle`, `screw`, and `capsule`. The reusable manifest, configuration, and
evaluation helpers live under `app/efficientad/`.

Install the pinned Kaggle experiment environment with
`requirements-kaggle-efficientad.txt`. The Kaggle-compatible pair is currently
PyTorch `2.6.0` and Torchvision `0.21.0` for the Python 3.13 notebook image.
The notebook uses the project's native EfficientAD-S implementation and removes
Kaggle's optional Transformers package because EfficientAD-S does not use it.
Training has **not** occurred merely
because the notebook exists; only a completed Kaggle run with recorded metrics,
checkpoint hashes, preprocessing metadata, and artifact manifest can qualify a
category. MVTec AD is CC BY-NC-SA 4.0 and must remain private unless its terms
permit the intended distribution or commercial use.

## Persistence status

The local SQLite inspection store in `app/persistence.py` is connected to the
HTTP API and offline workflow. It provides transactional creation,
idempotency-key replay protection, decision read-back, and immutable event rows.

## Documentation

- `docs/PROJECT_DOCUMENT_INDEX.md` — document inventory and missing Document 16.
- `docs/REPOSITORY_AUDIT.md` — evidence-based repository findings.
- `docs/REQUIREMENTS_TRACEABILITY.md` — requirement-to-code/test matrix.
- `docs/IMPLEMENTATION_ROADMAP.md` — dependency-aware implementation order.
- `docs/DECISIONS_AND_OPEN_QUESTIONS.md` — unresolved product/data/hardware questions.
- `docs/BASELINE_TEST_REPORT.md` — baseline commands and shell-execution blocker.

## Safety and readiness

Hardware actuation is absent and disabled by design. Do not use this slice to control a motor, servo, PLC, or production equipment. The project remains below Gate A verification until the test command has been executed in a functioning environment.
