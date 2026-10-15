# Baseline Test Report

**Date:** 2026-10-15  
**Status:** `PARTIALLY VERIFIED — project tests execute; Git metadata is unavailable`

## Commands intended

The repository audit requires the following read-only commands from the project root:

```text
git status --short
git branch --show-current
find . -maxdepth 3 -type f
```

No project-specific install, test, build, API, model, camera, or firmware command could be identified because no implementation manifests or source entry points are present.

## Observed execution failure

The available shell tool returned before command execution:

`omnirush sandbox: the sandbox is not reachable (dial tcp 127.0.0.1:42579: connect: connection refused); omnirush sandbox status says why`

Therefore the following are **not verified**:

- Git repository status, branch, commit, or history.
- Runtime versions and dependency installation.
- Application startup, API health, model import/inference, camera, firmware build, or tests.
- Docker build/run.

After the first policy slice was added, the intended focused command was also attempted:

```text
python3 --version
python3 -m unittest discover -s tests -v
```

It was blocked by the same shell-sandbox connection failure before the commands ran. The source files were inspected with the workspace file reader, but that is not a substitute for executing the test suite.

The latest verification attempt was:

```text
make test
```

It executed successfully after the shell became available and reported **21 tests passed**.

Additional successful check:

```text
python -m compileall -q app tests
```

An in-process `ThreadingHTTPServer` smoke test also passed for liveness,
inspection creation, `UNVERIFIED` fail-closed behavior, and event retrieval.

`git diff --check` could not be used because this workspace is not a Git repository. `git status --short` and the requested combined command reported that no Git repository exists.

## Current implementation additions not yet verified

Since the prior baseline, the workspace now contains:

- project-native PatchCore numerical core and optional WideResNet50-2 extractor;
- strict filesystem-only MVTec AD discovery/inventory;
- immutable artifact writers and release-manifest hashing;
- an offline inventory CLI;
- transactional SQLite inspection persistence with idempotency and event history;
- focused unit tests for those components.

The test suite now covers policy, PatchCore numerical/dataset/artifact behavior,
SQLite persistence, and the local API. No MVTec category, model release,
memory bank, benchmark score, camera run, firmware run, backup/restore drill,
or physical behavior has been executed. Persistence and API tests use local
in-memory/temp SQLite fixtures.

## Baseline conclusion

The current automated software slice has fresh evidence from `make test`: 21
tests passed. Model, dataset benchmark, camera, hardware, backup/restore, and
production readiness remain unverified or blocked.
