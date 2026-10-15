# Decisions and Open Questions

## Decisions made from available evidence

| ID | Decision | Basis | Consequence |
|---|---|---|---|
| DEC-001 | Local-first, fail-closed prototype | Documents 01, 03, 07, 09, 12 | Cloud is not required for core decisions; missing dependencies yield `UNVERIFIED`/hold. |
| DEC-002 | Deterministic policy is separate from model inference and hardware | Documents 04, 06, 07, PRD | No LLM or ESP32 may choose the terminal outcome. |
| DEC-003 | Actuation is disabled by default | Documents 02, 06, 10, 17 | Safe software-only work can proceed without hardware. |
| DEC-004 | Do not assume PatchCore settings or thresholds | Documents 03, 04, 13 | Real model/data must be supplied before qualification claims. |
| DEC-005 | Missing Document 16 is a blocker for complete document compliance | User request and file inventory | Backup/DR implementation can be designed from cross-references but cannot claim the full document set was read. |

## Open questions

| ID | Question | Evidence needed | Impact if unresolved |
|---|---|---|---|
| OQ-001 | Where is the actual application/firmware repository? | Git URL/archive and commit | Cannot preserve existing implementation or run baseline. |
| OQ-002 | What is the product category and defect taxonomy? | Dataset/model inventory and owner decision | Cannot choose conveyor geometry, thresholds, or quality claims. |
| OQ-003 | What model artifact and preprocessing are real? | Release manifest, weights/memory bank, code, hashes | Model path remains `BLOCKED`; only explicit simulation/testing is allowed. |
| OQ-004 | What camera/phone and transport are available? | Device model, Linux capture test, camera profile | Gate B blocked; stale-frame policy cannot be measured. |
| OQ-005 | What ESP32 board, firmware, motor, driver, servo, and sensor are available? | Part IDs, datasheets, firmware source/build | Gate C blocked; exact pins and limits must remain provisional. |
| OQ-006 | What are approved pass/fail thresholds and false-accept/reject costs? | Calibration and locked-test report | Automatic decisions remain unqualified. |
| OQ-007 | What retention and backup policy is required? | Owner/privacy decision and missing Document 16 | Evidence storage and restore targets remain provisional. |
| OQ-008 | What deployment access model is required? | Local-only versus LAN/multi-user decision | Authentication/authorization scope changes materially. |
| OQ-009 | Why does Document 01's historical sequence differ from actual Documents 08–12? | Owner clarification or canonical revision | Index records actual filenames; implementation should follow content and preserve discrepancy. |
| OQ-010 | Why is the shell sandbox unavailable? | OmniRush runtime repair | Baseline tests, git status, and commits cannot be verified until restored. |
