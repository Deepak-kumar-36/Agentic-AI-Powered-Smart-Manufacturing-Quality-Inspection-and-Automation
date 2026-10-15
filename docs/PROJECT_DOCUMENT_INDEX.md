# Project Document Index

**Inventory date:** 2026-10-15 (Asia/Calcutta)  
**Workspace:** `AI-Powered Smart Manufacture Quality Inspection`

## Inventory

| No. | Title | Actual path | Version/status | Notes |
|---:|---|---|---|---|
| 01 | Project Charter & Execution Roadmap | `Document_01_Project_Charter_Execution_Roadmap.md` | 1.0, initial build baseline | Defines tabletop scope, acceptance criteria, milestones, and safe boundaries. |
| 02 | Hardware Design & Bill of Materials | `Document_02_Hardware_Design_BOM.md` | 1.0, prototype design baseline | BOM and provisional mechanical/electrical design; exact parts are not frozen. |
| 03 | Repository Audit & Software Architecture | `Document_03_Repository_Audit_Software_Architecture.md` | 1.0, audit pending | Explicitly states that source code was unavailable when drafted. |
| 04 | Dataset & AI Model Qualification | `Document_04_Dataset_AI_Model_Qualification.md` | 1.0, qualification plan | PatchCore is an intended direction only; product and thresholds remain open. |
| 05 | Phone Camera & Laptop Setup | `Document_05_Phone_Camera_Laptop_Setup.md` | 1.0, compatibility unverified | Camera transport and freshness requirements. |
| 06 | ESP32 Firmware Specification | `Document_06_ESP32_Firmware_Specification.md` | 1.0, contract/specification | Bounded protocol and safe-state requirements; pins remain provisional. |
| 07 | Inspection API & Decision Engine | `Document_07_Inspection_API_Decision_Engine.md` | 1.0, proposed design | Canonical outcomes, API, persistence, idempotency, and action separation. |
| 08 | Operator Dashboard & Frontend Specification | `Document_08_Operator_Dashboard_Frontend_Specification.md` | 1.0, proposed design | UI state, operator workflow, accessibility, and action-status semantics. |
| 09 | End-to-End Integration & Verification Test Plan | `Document_09_End_to_End_Integration_Verification_Test_Plan.md` | 1.0, proposed test plan | Staged verification and failure cases; no execution evidence in source. |
| 10 | Deployment, Installation & Operations Runbook | `Document_10_Deployment_Installation_Operations_Runbook.md` | 1.0, proposed runbook | Local deployment, startup, recovery, backup, and supervised operation. |
| 11 | Model Monitoring, Drift Detection & Continuous Improvement | `Document_11_Model_Monitoring_Drift_Continuous_Improvement.md` | 1.0, proposed design | Telemetry, drift, review, and release governance. |
| 12 | Security, Threat Modeling & Data Protection | `Document_12_Security_Threat_Modeling_Data_Protection.md` | 1.0, proposed design | Threat register, local exposure, bounded actuation, privacy, and recovery. |
| 13 | Dataset Governance, Annotation & Model Release Workflow | `Document_13_Dataset_Governance_Annotation_Model_Release_Workflow.md` | 1.0, proposed workflow | Provenance, labels, split integrity, manifests, approvals, and rollback. |
| 14 | Observability, Logging, Metrics & Incident Response | `Document_14_Observability_Logging_Metrics_Incident_Response.md` | 1.0, proposed target design | Correlation, structured events, metrics, readiness, and incident playbooks. |
| 15 | Performance Engineering, Capacity Planning & Reliability Budgets | `Document_15_Performance_Engineering_Capacity_Planning_Reliability_Budgets.md` | 1.0, proposed benchmark plan | End-to-end timing and reliability measurement; no claimed numbers. |
| 16 | Backup, Disaster Recovery & Business Continuity | **Missing** | Not accessible | No file matching `Document_16*` exists in the workspace. Backup requirements are referenced by Documents 10, 12, 15, and 17. |
| 17 | Production Readiness Review & Go/No-Go Assessment | `Document_17_Production_Readiness_Go_No_Go_Assessment.md` | 1.0, assessment template | Gate A–E readiness vocabulary and evidence bundle. |

## Additional specification

| File | Role |
|---|---|
| `Production_Grade_Agentic_Manufacturing_Quality_Inspection_PRD.md` | Production target-state PRD v3.0; explicitly says implementation and benchmark claims require verification. |

## Format and duplicate review

- Accessible source format: Markdown only.
- Word documents (`.doc`, `.docx`): none found.
- Duplicate numbered versions: none found.
- Competing content: Document 01's historical “required document sequence” labels differ from the actual filenames/topics for Documents 08–12; the actual numbered filenames and contents are used as the current document index, with the discrepancy recorded in `docs/DECISIONS_AND_OPEN_QUESTIONS.md`.

## Cross-document requirements

The documents consistently require: local-first operation; explicit `PASS`/`FAIL`/`UNVERIFIED`; deterministic policy separated from model inference; durable evidence and event history; idempotency; bounded ESP32 commands; explicit ACK versus completion; safe hold on uncertainty; structured observability; versioned model/policy artifacts; dataset provenance and leakage controls; tested backup/restore; and gate-specific evidence.

## Reading limitation

The expected Document 16 is unavailable, so its requirements cannot be claimed as read. No implementation or readiness decision should rely on an unstated interpretation of that missing document.
