# Local Development and Operations Guide

This guide explains how to install, test, start, and use the Smart Manufacturing
Quality Inspection project locally.

The project is local-first. The normal development flow uses:

- A Python HTTP API backend on `127.0.0.1:8000`.
- A dependency-free static browser dashboard on `127.0.0.1:4173`.
- A SQLite database under `data/`.
- A local image root for uploaded or model-scored images.

The current default API is safe for development: without an explicitly injected
model and policy, inspections are persisted as `UNVERIFIED` with
`MODEL_NOT_READY`. The dashboard does not make AI decisions in the browser.

## 1. Prerequisites

Required:

- Linux or another POSIX-like development environment.
- Python 3.12.x. The repository pins `3.12.0` in `.python-version`.
- `make`.

Optional:

- Node.js for dashboard contract tests. The repository pins Node.js `22.20.0`
  in `.nvmrc` when that file is available.
- Docker for the reproducible offline test image.
- A reviewed EfficientAD release, compatible checkpoints, teacher weights, and
  an image directory for model-backed inference. These are not included in Git.

No physical phone, conveyor, ESP32, GPU, external network, or real dataset is
needed for the default development flow or test suite.

## 2. Enter the repository

```bash
cd /path/to/your/checkout
```

Replace `/path/to/your/checkout` with the path of your own checkout, or run the
command from the repository root. Do not hard-code a developer machine's path
into application configuration or committed documentation.

Check the current branch and working tree before making changes:

```bash
git branch --show-current
```

Preserve unrelated working-tree changes and the local `.opencode/` directory.

## 3. Create the Python environment

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --requirement requirements.lock
```

Confirm the interpreter and package installation:

```bash
python --version
python -m pip check
```

All Python commands below assume that `.venv` is activated. If it is not
activated, call `.venv/bin/python` explicitly instead of installing globally.

The lockfile intentionally does not install the workstation-specific
Torch/torchvision/scipy stack or model weights. The dependency-lazy model code
and the offline tests work without those optional artifacts.

## 4. Run the complete test suite

```bash
make test
```

This runs the Python unittest suite and, when Node.js is installed, the
dependency-free dashboard tests. The Python tests are offline and do not require
model weights or hardware.

Run the required checks individually when debugging a change:

```bash
python -m unittest discover -s tests -v
node tests/dashboard_analytics.test.cjs
python -m compileall -q app tests
```

If Node.js is unavailable, the dashboard test is an explicit optional skip.

## 5. Start the backend API

### 5.1 Dependency-free development backend

Open **Terminal 1** from the repository root:

```bash
source .venv/bin/activate
python -c 'from app.api import serve; serve()'
```

The API listens on:

```text
http://127.0.0.1:8000
```

It uses an in-memory database when started through this short development
command. For persistent inspection history, use the reproducible server command
below with `--db data/inspection.sqlite3`.

Check that the backend is running:

```bash
curl http://127.0.0.1:8000/health/live
curl http://127.0.0.1:8000/health/ready
curl http://127.0.0.1:8000/api/v1/system/status
curl http://127.0.0.1:8000/api/v1/system/metadata
```

Expected development behaviour without an injected model is `MODEL_NOT_READY`
and `UNVERIFIED`; this is intentional and is not a model failure.

### 5.2 Persistent model-backed server

Only use this command after a reviewed release has been explicitly qualified.
The paths below are examples and must be replaced with real local artifact paths:

```bash
source .venv/bin/activate
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

The threshold values above are placeholders, not recommendations. The reviewed
release loader rejects unqualified metadata, missing hashes, incompatible
artifacts, and missing category thresholds.

For a CPU-capable reviewed environment, use the project/runtime-supported CPU
device instead of `cuda`. Do not install or download model weights as part of
this guide.

## 6. Start the frontend dashboard

Open **Terminal 2** from the repository root. Keep the API running in Terminal 1.

```bash
python -m http.server 4173 --directory dashboard
```

Open this URL in a browser:

```text
http://127.0.0.1:4173/?api=http://127.0.0.1:8000
```

The `api` query parameter selects the backend origin. The dashboard is static;
the backend must be running separately. It provides:

- Inspection submission and history.
- Evidence and event timeline display.
- Human review submission and review history.
- Review coverage, agreement, disagreement, conflict, and attention analytics.
- Reviewed-evidence export preview and ZIP download.
- Runtime, metadata, health, and read-only dataset/training context.

Stop either server with `Ctrl-C`.

## 7. Submit an inspection manually

The API requires an `Idempotency-Key` for inspection creation. This example
creates a record without a model and therefore returns `UNVERIFIED`:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/inspections \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: local-example-001' \
  -d '{"category":"bottle"}'
```

List recent records:

```bash
curl 'http://127.0.0.1:8000/api/v1/inspections?limit=50'
```

Retrieve a record and its immutable event timeline:

```bash
curl http://127.0.0.1:8000/api/v1/inspections/INSPECTION_ID
curl http://127.0.0.1:8000/api/v1/inspections/INSPECTION_ID/events
```

Replace `INSPECTION_ID` with the ID returned by the API. Do not use a literal
placeholder when calling the endpoint.

## 8. Add a human review

Human reviews are additive. They do not change the original AI outcome, score,
model version, evidence, or event history.

```bash
curl -X POST \
  http://127.0.0.1:8000/api/v1/inspections/INSPECTION_ID/reviews \
  -H 'Content-Type: application/json' \
  -d '{"outcome":"CONFIRMED_NORMAL"}'
```

For a defect review:

```bash
curl -X POST \
  http://127.0.0.1:8000/api/v1/inspections/INSPECTION_ID/reviews \
  -H 'Content-Type: application/json' \
  -d '{"outcome":"CONFIRMED_DEFECT","defect_type":"scratch"}'
```

Supported defect types are `scratch`, `dent`, `crack`, `contamination`,
`misalignment`, and `other`. `INCONCLUSIVE` is also supported, but it is not an
eligible definitive export label.

Read review history:

```bash
curl http://127.0.0.1:8000/api/v1/inspections/INSPECTION_ID/reviews
curl 'http://127.0.0.1:8000/api/v1/review-analytics?review_state=ATTENTION'
```

## 9. Export reviewed evidence

From the dashboard, use **Review Analytics → Download eligible ZIP**. The API
equivalents are:

```bash
curl -OJ 'http://127.0.0.1:8000/api/v1/review-export/download'
```

The export includes only readable, valid, hash-verified, definitively reviewed,
non-conflicting records. The human review supplies the label. `UNVERIFIED` AI
outcomes can still be included when the human review is definitive.

The ZIP contains:

```text
images/
manifest.jsonl
exclusions.csv
README.md
```

It is candidate evidence, not approved training data. No split assignment,
training, threshold calibration, deployment, or release qualification occurs.

## 10. Validate and stage an exported ZIP

The ZIP path must be a real path. The example name below is not created by the
repository automatically.

```bash
python -m app.dataset_intake validate \
  /real/path/reviewed-inspection-evidence-20261020T123456Z.zip \
  --report validation.json
python -m json.tool validation.json
```

Only stage after the report status is `VALID` or `VALID_WITH_WARNINGS`:

```bash
python -m app.dataset_intake stage \
  /real/path/reviewed-inspection-evidence-20261020T123456Z.zip \
  --staging-root data/reviewed-staging \
  --report staging-result.json
```

The reports are exclusive-create outputs. Choose a new report filename if one
already exists. The validator rejects unsafe archive members, corrupt images,
hash mismatches, invalid labels, duplicate content, inconsistent counts,
sensitive metadata, and resource-limit violations. Warnings may indicate missing
physical-sample/session metadata, low sample counts, class imbalance, incomplete
defect coverage, or unverified provenance.

### Fish shell note

Fish reports an error when a wildcard matches no files. Do not run an unmatched
pattern such as `reviewed-inspection-evidence-*.zip`. Use the exact downloaded
path instead. To discover ZIPs in Downloads without an unmatched-glob error:

```fish
for file in ~/Downloads/*.zip
    if test -f "$file"
        echo "$file"
    end
end
```

The staging operation creates a generated `candidate-<UUID>` directory with
verified images, a remapped manifest, `staging-manifest.json`, and
`validation-report.json`. It never overwrites an existing candidate or modifies
the source ZIP or active datasets.

## 11. Docker verification

The Dockerfile builds a Python 3.12 test image and runs the offline suite:

```bash
docker build -t manufacturing-inspection:test .
docker run --rm manufacturing-inspection:test
```

The image does not download weights, enable hardware, or start the browser
dashboard.

## 12. Troubleshooting

### `SOURCE_UNREADABLE`

The package path does not exist, is not readable, or is still a placeholder.
Use `pwd`, `ls -la`, or the real browser download path. The validator does not
invent or locate a package for you.

### Fish says `No matches for wildcard`

No file matched the wildcard. Use the exact filename or the fish-safe loop in
the Fish shell note above.

### `Dataset intake failed` while using `--report`

Report output is intentionally non-overwriting. Pick a new filename such as
`validation-2.json`. For a missing package, replace the example package path
before retrying.

### Dashboard is offline

Confirm Terminal 1 is running the API on port 8000, Terminal 2 is serving the
`dashboard` directory on port 4173, and the browser URL includes the correct
`?api=http://127.0.0.1:8000` origin.

### Results are `UNVERIFIED`

This is expected from the dependency-free backend. It means no configured
server-side model/policy was available. The API refuses client-supplied AI
decisions and scores.

### Port already in use

Start either service on another local port using the project entry point/options,
then update the dashboard `api` URL accordingly. Do not create a second API
process against the same persistent database without understanding its lifecycle.

## 13. Safe shutdown and reset

Stop the API and dashboard with `Ctrl-C`. The persistent SQLite database and
local staged data are under ignored `data/` paths when those options are used.
Do not delete them blindly if the inspection history or staged candidate is
needed. The default short API command uses in-memory state and loses it on exit.
