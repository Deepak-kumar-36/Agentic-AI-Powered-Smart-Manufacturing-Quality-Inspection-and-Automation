# Implementation Roadmap

## Critical path

1. Establish a reproducible local Python runtime, lockfile, Dockerfile, and one offline test command.
2. Implement typed inspection outcomes, reason codes, versioned decision policy, and fail-closed evaluation.
3. Add durable local persistence and idempotency/read-back behavior.
4. Add API health/readiness and inspection endpoints around the persistent core.
5. Integrate a real, qualified model artifact only after its dataset, preprocessing, score semantics, and hash are supplied.
6. Add a real camera adapter and stale-frame validation; keep actuation disabled.
7. Add dashboard states from the real API.
8. Add simulated ESP32 protocol and action ledger; only then consider firmware integration.
9. Add observability, backup/restore, benchmark, security, and release evidence.
10. Perform supervised hardware verification only after Gate A/B evidence and hardware-specific safety review.

## Parallelizable work

- Dataset manifest and license/provenance tooling once data is supplied.
- Host-side ESP32 protocol parser/simulator while the board is unavailable.
- Dashboard contract/state components after API schemas stabilize.
- Operational runbook and evidence templates, without claiming execution.

## First vertical slice selected

The first safe slice is the deterministic policy core. It has no hardware or external model dependency, can be tested offline, and closes the highest-risk integrity gap: invalid evidence must never become `PASS`. It will support explicit model-unavailable and malformed-output paths as `UNVERIFIED`.

## Stop conditions

- Do not enable physical actuation without real controller identity, protocol tests, physical disconnect, and supervised Gate C evidence.
- Do not select product category or thresholds without actual dataset/model qualification evidence.
- Do not claim model performance, camera verification, backup restore, or production readiness without executed evidence.
