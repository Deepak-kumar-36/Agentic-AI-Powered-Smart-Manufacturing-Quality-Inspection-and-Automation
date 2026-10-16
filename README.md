# Smart Manufacturing Quality Inspection

Local-first foundation for a traceable manufacturing visual-inspection platform.

## Current evidence boundary

The workspace initially contained engineering specifications but no application or firmware repository, model artifact, dataset, camera, or ESP32 hardware. The current implementation therefore contains only the first safe vertical slice: a dependency-free deterministic decision policy. It does **not** claim genuine model inference, camera integration, persistence, dashboard functionality, firmware behavior, hardware verification, or production readiness.

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
Until a qualified model and camera are configured, every submitted inspection
is durably recorded as `UNVERIFIED` with `MODEL_NOT_READY`; client-supplied
scores and outcomes are not trusted.

## Kaggle EfficientAD-S experiments

The Kaggle entry point is `notebooks/efficientad_s_kaggle.ipynb`. It expects
the authorized MVTec AD dataset attached at
`/kaggle/input/datasets/ipythonx/mvtec-ad`, validates the MVTec layout, and starts with
`bottle`, `screw`, and `leather`. The reusable manifest, configuration, and
evaluation helpers live under `app/efficientad/`.

Install the pinned Kaggle experiment environment with
`requirements-kaggle-efficientad.txt`. The Kaggle-compatible pair is currently
PyTorch `2.6.0` and Torchvision `0.21.0` for the Python 3.13 notebook image.
It also pins the Transformers/Hugging Face versions because Kaggle's
preinstalled `huggingface-hub 2.x` is incompatible with the Anomalib/Lightning
import path.
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
