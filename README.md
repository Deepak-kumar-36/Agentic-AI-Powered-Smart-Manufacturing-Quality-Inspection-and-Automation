# Smart Manufacturing Quality Inspection

Local-first foundation for a traceable manufacturing visual-inspection platform.

## Current evidence boundary

The workspace initially contained engineering specifications but no application or firmware repository, model artifact, dataset, camera, or ESP32 hardware. The current implementation contains a dependency-free deterministic decision policy, a dependency-lazy native EfficientAD-S checkpoint adapter, and a hardware-neutral V4L2 frame adapter. It does **not** claim live camera qualification, dashboard functionality, firmware behavior, hardware verification, or production readiness.

`PASS`, `FAIL`, and `UNVERIFIED` are explicit. Invalid/stale input, unavailable models, invalid scores, and incompatible model releases fail closed to `UNVERIFIED`.

## Runtime

- Python 3.12.x, pinned by `.python-version` and `pyproject.toml`.
- NumPy is pinned in `pyproject.toml` and `requirements.lock` for PatchCore's
  numerical core.
- Torch/torchvision/Pillow/scipy remain optional until the workstation runtime
  and explicit weight-acquisition procedure are verified.

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
HTTP API is intentionally not wired to these artifacts until a full Kaggle run
has been reviewed and the release thresholds are approved.

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

Submit a server-scored inspection using an image below `--image-root`:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/inspections \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: local-smoke-001' \
  -d '{"category":"bottle","image_path":"sample.png"}'
```

The client must not send `score` or `outcome`; those fields are ignored and the
decision is produced only from the configured server-side model and policy.

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
The phone adapter is transport-ready, but it is not yet wired to a live model
decision loop or physical actuation.

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

The first local SQLite inspection store is present in `app/persistence.py` with
transactional creation, idempotency-key replay protection, decision read-back,
and immutable event rows. It is not yet connected to an HTTP API or a real
PatchCore release.

## Documentation

- `docs/PROJECT_DOCUMENT_INDEX.md` — document inventory and missing Document 16.
- `docs/REPOSITORY_AUDIT.md` — evidence-based repository findings.
- `docs/REQUIREMENTS_TRACEABILITY.md` — requirement-to-code/test matrix.
- `docs/IMPLEMENTATION_ROADMAP.md` — dependency-aware implementation order.
- `docs/DECISIONS_AND_OPEN_QUESTIONS.md` — unresolved product/data/hardware questions.
- `docs/BASELINE_TEST_REPORT.md` — baseline commands and shell-execution blocker.

## Safety and readiness

Hardware actuation is absent and disabled by design. Do not use this slice to control a motor, servo, PLC, or production equipment. The project remains below Gate A verification until the test command has been executed in a functioning environment.
