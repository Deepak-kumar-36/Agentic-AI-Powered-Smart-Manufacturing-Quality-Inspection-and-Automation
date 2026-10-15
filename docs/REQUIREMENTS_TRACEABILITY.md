# Requirements Traceability Matrix

This is the initial evidence-based matrix. `PLANNED` means the requirement is specified but not proven by an implementation or test. `BLOCKED` means a required external artifact or execution capability is missing.

| ID | Source | Requirement | Priority | Existing implementation | Evidence | Gap | Implementation task | Verification | Status |
|---|---|---|---|---|---|---|---|---|---|
| CORE-001 | Doc 01 §3; Doc 07 §7 | Produce only `PASS`, `FAIL`, or `UNVERIFIED` | Critical | Implemented, not verified | `app/policy.py` | Test execution unavailable | Keep typed outcome enum and policy engine | Boundary/unit tests | Implemented not verified |
| CORE-002 | Doc 01 §3; Doc 04 §13 | Invalid/missing/stale/model-error input cannot become `PASS` | Critical | Implemented, not verified | `app/policy.py`, `tests/test_policy.py` | Test execution unavailable | Keep explicit reason-coded fail-closed mapping | Invalid-input tests | Implemented not verified |
| CORE-003 | Doc 07 §7.2 | Versioned deterministic thresholds with exact boundary semantics | Critical | Absent | Specifications only | No policy schema or release metadata | Add immutable policy model and compatibility checks | Below/equal/inside/above boundary tests | In progress |
| CORE-004 | Doc 07 §8; Doc 09 §4 | Persist traceable inspection, evidence, model/policy, and events | Critical | Absent | No DB/schema found | No persistence | Add local durable store and read-back tests | Restart/read-back and failure tests | Planned |
| CORE-005 | Doc 07 §9 | Idempotent inspection creation and action commands | Critical | Absent | Specifications only | No ledger | Add idempotency-key/request-hash contract | Replay and conflict tests | Planned |
| CAP-001 | Doc 05 §8 | Capture adapter records fresh frame identity/metadata | High | Absent | No camera code | No adapter | Add interface and stale-frame guard | Fresh/stale/disconnect tests | Blocked by camera |
| ML-001 | Doc 04 §4 | Model adapter returns typed score semantics and artifact identity | Critical | Absent | No model artifacts | No qualified model | Add adapter boundary; wire real artifact when supplied | Schema and artifact-integrity tests | Blocked by model |
| ML-002 | User continuation §2; Doc 04 §4–5 | Project-native PatchCore numerical core with layer2/layer3-compatible embedding path | Critical | Implemented, not verified | `app/patchcore/core.py` | Real torch weights/runtime not verified | Run dependency-backed extractor and benchmark when runtime is available | Shape, finiteness, scoring, heatmap tests | Implemented not verified |
| ML-003 | User continuation §2.3–4 | Category-specific MVTec discovery and strict dataset validation | Critical | Implemented, not verified | `app/patchcore/dataset.py`, `app/patchcore/cli.py` | Official dataset absent | Inventory actual MVTec root and build category banks | Fixture and real-dataset inventory | Implemented not verified |
| ML-004 | User continuation §2.3; Doc 13 | Immutable hashed model/memory-bank artifacts | High | Implemented, not verified | `app/patchcore/artifacts.py` | No real release artifact | Build release manifest from actual bank | Hash/overwrite/no-pickle tests | Implemented not verified |
| API-001 | Doc 07 §5 | Health/readiness and inspection resource API | High | Implemented, software-only verified | `app/api.py`, `tests/test_api.py`, HTTP smoke command | Model/camera unavailable; no external process deployment | Connect qualified model and camera adapters | API contract and HTTP smoke tests | Software-only verified |
| DB-001 | User continuation §7; Doc 07 §8 | Transactional local inspection records and immutable events | Critical | Implemented, not verified | `app/persistence.py` | Shell execution unavailable | Connect store to API/model flow | Read-back/restart/idempotency tests | Implemented not verified |
| HW-001 | Doc 06 §6–8 | Firmware accepts only bounded, versioned, idempotent commands | Critical | Absent | No firmware source | No controller | Add protocol package/simulator only | Malformed/duplicate/unknown command tests | Blocked by firmware |
| UI-001 | Doc 08 §5 | Dashboard separates outcome from physical action state | High | Absent | No frontend source | No UI | Add UI after API contract exists | Component/integration tests | Planned |
| OPS-001 | Doc 14 §4 | Liveness and readiness are distinct and redacted | High | Absent | No runtime | No health implementation | Add status contracts and structured events | Health/readiness tests | Planned |
| SEC-001 | Doc 12 §6 | Loopback-safe binding and validated inputs | Critical | Absent | No runtime | No security boundary | Default local binding and strict schemas | Binding/input tests | Planned |
| DATA-001 | Doc 13 §4–9 | Dataset provenance, hashes, labels, grouped splits | High | Absent | No dataset | No governance artifacts | Add manifest/qualification workflow when data supplied | Manifest and leakage checks | Blocked by dataset |
| DR-001 | Documents 10, 12, 15, 17 | Tested backup/restore and recovery | High | Absent | Document 16 missing | No backup design or test | Recover missing document and add local restore runbook | Clean-location restore test | Blocked |
| REL-001 | Doc 15 §4–9 | Measure full-cycle latency and failure counts | Medium | Absent | No runtime | No telemetry | Add monotonic stage timings and export | Benchmark command with raw samples | Planned |
| REL-002 | Doc 17 §52–90 | Keep actuation disabled until Gate C evidence exists | Critical | No actuator path exists | `README.md`, no firmware/API source | Hardware path not implemented | Preserve disabled-by-absence default and add explicit config when controller exists | Configuration and protocol tests | Implemented not verified |

## Current gate assessment

- Gate A (software development/testing): `NOT VERIFIED` — runtime and test command are not yet available.
- Gate B (live camera): `BLOCKED` — camera and adapter absent.
- Gate C (supervised tabletop hardware): `BLOCKED` — hardware, firmware, protocol, and safety evidence absent.
- Gate D/E: `NOT APPLICABLE TO CURRENT EVIDENCE`; no pilot or production claim is permitted.
