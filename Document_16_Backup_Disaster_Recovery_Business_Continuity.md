# Document 16 — Backup, Disaster Recovery & Business Continuity Plan

**Project:** Agentic AI Smart Manufacturing Quality Inspection & Automation Platform  
**Document type:** Recovery and continuity engineering specification  
**Version:** 1.0  
**Status:** Proposed plan; actual backup implementation and recovery timings are unverified  
**Target deployment:** Local-first tabletop prototype using a phone camera, Linux/Arch workstation, inspection service, anomaly-detection model, local database/artifact store, dashboard, and ESP32-class low-voltage hardware.

---

## 1. Purpose

Define how the platform protects its data and configuration, recovers from accidental deletion or corruption, and resumes operation without losing track of an inspection or physical item.

The primary recovery goal is not merely to make the application launch again. The system must restore a known, compatible combination of application version, model artifact, preprocessing configuration, decision policy, database, camera setup, and firmware. Any in-flight item or machine command must be reconciled before the conveyor sequence resumes.

This plan is a **proposed specification**. It does not claim that automated backups, off-device copies, database migrations, or tested restores currently exist. Confirm the actual repository, storage paths, database backend, firmware source, and deployment procedure before implementing the runbooks.

## 2. Recovery principles

1. **Recover a consistent system, not just individual files.** Application code, database schema, model release, preprocessing, policy, and firmware must be mutually compatible.
2. **Preserve evidence before repair.** Do not overwrite the only copy of a corrupted database, log, model artifact, or incident record.
3. **Backups are not proven until restored.** A successful copy command is not a successful recovery test.
4. **Keep a recoverable copy off the primary workstation.** A backup on the same disk does not protect against drive failure, theft, or filesystem loss.
5. **Separate reproducible code from irreplaceable data.** Source code may be rebuilt from version control; inspection history, curated labels, configuration, manifests, and specific model artifacts may not be reproducible.
6. **Do not restore blindly over newer evidence.** Preserve the current failed state when feasible and record which backup and timestamp are being restored.
7. **Fail closed during uncertainty.** If the application cannot verify model/policy identity, persistence health, current item identity, or machine state, keep the workflow in hold/manual review and do not infer `PASS`.
8. **No automatic motion after recovery.** Service restart must not resume the conveyor or replay actuator commands without reconciliation and explicit supervised arming.
9. **Offline recovery is required.** Core recovery steps must not depend on cloud access; optional cloud sync can be restored later.
10. **Prototype boundary.** This plan supports a supervised low-voltage tabletop prototype, not a certified industrial control or business-continuity system.

## 3. Recovery objectives and terminology

Choose and approve concrete targets after measuring the importance and volume of the data. Do not adopt arbitrary recovery times without checking feasibility.

- **RPO — Recovery Point Objective:** maximum acceptable amount of recent data that could be lost, expressed as time or transactions.
- **RTO — Recovery Time Objective:** target elapsed time to restore the required service to an agreed usable state.
- **MTTR — Mean Time to Restore/Repair:** observed average recovery time over incidents or drills; this is a measurement, not a promise.
- **Backup age:** time since the last successful verified backup.
- **Restore point:** one versioned, identifiable backup set with manifest and integrity hashes.
- **Recovery mode:** software-only operation, camera-connected inspection, or supervised hardware operation. These modes have different prerequisites.
- **Reconciliation:** determining the actual state of an in-flight inspection, physical item, and machine command using durable records and physical evidence.

### 3.1 Recovery target worksheet

| Data/service | Proposed RPO decision | Proposed RTO decision | Required evidence |
|---|---|---|---|
| Source code and build/dependency manifests | Decide based on version control/remote copy | Decide for a clean rebuild | Commit reference and reproducible setup notes |
| Model artifacts and manifests | Decide whether artifact can be regenerated exactly | Decide based on artifact size and transfer time | Hash-verified artifact and model-load test |
| Decision policy/configuration | Tight tolerance; versions must be traceable | Restore before any decisions are made | Policy version and threshold configuration verified |
| Inspection database/events | Define acceptable loss of inspection history | Restore before new durable inspections | Integrity check and reference-count validation |
| Images/heatmaps/other artifacts | Set retention and loss tolerance by evidence need | Restore only required data before operation | Hash and database-reference reconciliation |
| Camera setup/config | Recreate from documented setup; define evidence needed | Confirm fresh valid frame before camera readiness | Setup record and reference-frame check |
| ESP32 firmware/config | Keep source/build/version recoverable | Verify device identity and behavior before arming | Firmware identity and safe bench test |
| Logs/incident records | Preserve active incidents; define routine retention | Must be available for incident analysis | Log bundle and time/version metadata |
| Secrets/credentials | Do not back up in plain text | Recover or rotate securely | Secret inventory; no values in recovery logs |

Fill in specific values, owners, storage locations, and review dates during implementation. Mark targets as **not established** until they have been tested.

## 4. Assets and backup classification

### 4.1 Critical to recreate or restore
- Source repository and exact revision used for a release.
- Dependency lockfiles, runtime versions, build scripts, and firmware source.
- Model weights/artifacts, memory bank if stored separately, configuration, and release manifests.
- Decision-policy configuration and its versioned approvals.
- Database schema/migrations, inspection records, state-transition events, review records, and machine-command lifecycle records.
- Required images, heatmaps, labels, split manifests, dataset manifests, hashes, and evaluation reports.
- Camera settings, service configuration, serial-device mapping, and installation/runbook versions.
- Incident and recovery records needed to preserve audit continuity.

### 4.2 Reproducible or replaceable, but still document
- System packages and package lists.
- Temporary caches, compiled caches, generated previews, and disposable logs outside active incidents.
- Frontend build output if the source and lockfile are safely stored.
- Derived artifacts that can be deterministically regenerated and re-verified.

Never classify data as disposable merely because its file extension looks temporary. Confirm whether an artifact is needed to reproduce the actual model output or reconstruct an inspection record.

### 4.3 Secrets
Secrets require a separate policy. Do not copy credentials into general backup bundles. If a secret store or encrypted backup is necessary, restrict access, document restore/rotation steps, and verify that recovery logs do not expose secret values. If a credential was exposed, rotate it rather than trusting a backup copy.

## 5. Backup architecture for the prototype

A reasonable starting design is:

1. **Version control:** source code, dependency manifests, scripts, documentation, schemas, and non-secret configuration.
2. **Local application backup:** database-consistent snapshot, model release manifest, required model/artifact files, data manifests, and approved configuration.
3. **Separate physical/off-device copy:** encrypted removable storage or another approved destination not on the primary workstation disk.
4. **Optional later off-site copy:** only after access, retention, privacy, and connectivity are defined.
5. **Restore verification area:** restore into a separate directory or test environment before replacing an active installation.

A simple three-copy/two-media/one-off-site approach may be useful as a general planning heuristic, but the project should choose a backup design it can actually maintain and test. Do not claim a formal 3-2-1 implementation unless the copies and media separation have been verified.

### 5.1 Suggested backup set contents
- `backup_manifest.json` or equivalent with backup ID, creation time, source machine/application version, database snapshot ID, code revision, model release, policy version, and file inventory.
- Database-consistent export/snapshot.
- Required image/artifact directories or an explicitly documented subset/retention scope.
- Model artifacts and release manifests, verified against recorded hashes.
- Dataset and split manifests, annotation versions, evaluation reports, and licences where applicable.
- Application and firmware source revision plus lockfiles/build notes.
- Non-secret runtime configuration and camera/hardware configuration records.
- Recent audit/incident logs or an incident-specific bundle.
- Hash file for backup contents and a backup verification report.

Include a scope statement indicating which data is deliberately excluded and how it can be regenerated.

## 6. Backup consistency requirements

### 6.1 Database consistency
- Use the database engine’s documented backup/snapshot mechanism rather than copying a live database file blindly.
- If using SQLite, identify whether the application uses WAL mode and use a consistent backup method that includes the committed database state. Do not assume copying only the main database file captures all committed changes.
- Record schema version and migration state.
- Check foreign-key/reference integrity after restore.
- Do not mix a database snapshot from one point in time with artifact directories from an unrelated point if their references can disagree.
- Pause new inspections or use a verified snapshot mechanism during backup to avoid capturing a partial multi-file state.

### 6.2 Artifact consistency
- Store large images and heatmaps outside the relational database when appropriate, but back up the file and database reference consistently.
- Use hashes to detect corruption or a wrong file.
- Do not overwrite a model release artifact in place; restore immutable release IDs.
- Retain dataset/split manifests used for qualification and ensure the restored artifact hash matches the model registry/manifest.

### 6.3 Configuration consistency
- Back up exact camera configuration, capture preprocessing, active model release, active policy, API/schema version, and ESP32 firmware identity as one compatibility record.
- Never recover a newer decision policy against an older model artifact unless compatibility has been explicitly verified and approved.
- Keep secrets out of general bundles; document a secure process to recreate or rotate them.

## 7. Backup schedule and retention

Set frequency based on data change rate and chosen RPO. A starting schedule to evaluate—not an automatically approved commitment—is:

- **Before each model/policy/firmware release:** create a named recovery point and preserve the currently qualified versions.
- **Before a major schema or configuration change:** backup database, application configuration, manifests, and active releases.
- **After a meaningful data collection/annotation session:** snapshot changed source data, labels, and manifest changes.
- **At the end of an important demo/test session:** export inspection history, relevant artifacts, logs, and a run manifest.
- **Periodic routine backup:** set a cadence that fits actual inspection volume and acceptable loss tolerance.
- **Before cleanup:** verify that a separate recoverable copy exists for any item that may be deleted.

Retention should distinguish routine data from unresolved incidents and qualification evidence. Avoid retaining all images forever by accident, but do not purge the only evidence associated with an open incident, model qualification, or disputed inspection. Record the retention period, storage owner, deletion method, and exceptions.

## 8. Backup verification and restore drills

Each backup operation should report:
- backup ID and creation timestamp;
- source revision, model release ID, policy version, database schema version;
- file count and total bytes;
- successful/failed files and exclusions;
- hashes generated and verified;
- database consistency result;
- destination and media/location classification;
- completion status and errors;
- operator/process identity.

### 8.1 Verification levels
- **Level 1 — Copy verification:** files exist, sizes are plausible, hashes match.
- **Level 2 — Data consistency:** database opens, integrity/foreign-key checks pass where supported, artifacts resolve, model manifest aligns with model files.
- **Level 3 — Functional restore:** application can read restored data, load the intended model/policy, pass health checks, and run a software-only smoke inspection.
- **Level 4 — Supervised system restore:** camera and ESP32 identities are verified, hardware remains disabled during smoke tests, in-flight state is reconciled, and an operator explicitly approves arming.

A Level 1 hash check alone is not evidence of full recoverability.

### 8.2 Restore-drill cadence
Define a cadence the team can sustain. At minimum, perform a restore drill before an important demonstration or major release, and repeat after material changes to the database, storage layout, model artifacts, or deployment process. Record each drill’s pass/fail, elapsed time, missing items, and corrective actions.

## 9. Recovery priorities

Recommended order:
1. Make the physical setup safe and determine whether an item or actuator is in an unknown state.
2. Preserve current evidence and identify the incident/recovery point.
3. Restore required host/runtime prerequisites.
4. Restore source revision and dependency environment or install a known-good build.
5. Restore verified model artifact, preprocessing metadata, and decision policy.
6. Restore database and artifact references as a consistent set.
7. Verify configuration, camera source, firmware identity, and logs.
8. Run software-only smoke tests.
9. Run live-camera tests with actuators disabled.
10. Reconcile current physical item and outstanding machine commands.
11. Obtain operator approval and arm the supervised tabletop mode only after all checks pass.

If only software work is required, it may be possible to restore in software-only mode while hardware remains disabled. Do not skip state reconciliation merely to get the UI running quickly.

## 10. Disaster recovery playbooks

### DR-01 — Accidental deletion or overwritten configuration
1. Stop configuration changes and, if decisions may be affected, stop automatic inspection.
2. Preserve the current configuration and event logs before restoring.
3. Identify the exact file/version and the last known good copy.
4. Restore into a temporary location and compare hashes/content.
5. Verify model/policy/camera compatibility and review differences.
6. Replace active configuration through a controlled change with a new audit event.
7. Run configuration, readiness, and software-only smoke tests.
8. Record the recovery point and approval.

### DR-02 — Database corruption or inconsistent migration
1. Stop new inspections requiring durable records; hold any in-flight item.
2. Preserve the corrupted database, WAL/journal files if applicable, logs, and schema/migration version.
3. Do not run repair tools on the only copy.
4. Restore a copy of the most appropriate consistent backup into a separate location.
5. Run database integrity checks, schema checks, and foreign-key/reference verification where supported.
6. Verify that required images, heatmaps, and model manifests exist for database references.
7. Reconcile records created after the backup from surviving logs, but do not invent or silently reconstruct outcomes.
8. Run application read, write, and software-only inspection tests.
9. Document any known history gap and get approval before resuming.

### DR-03 — Model artifact missing or corrupted
1. Mark model readiness false; do not reuse cached output or select a random artifact.
2. Preserve error logs and the failed artifact’s ID/hash.
3. Find the immutable qualified release matching the required manifest.
4. Restore the artifact and verify its cryptographic hash.
5. Confirm the matching preprocessing/runtime and decision policy are available.
6. Load the model with actuators disabled and run model readiness plus regression checks.
7. Record the active release and approval before inspections resume.

### DR-04 — Workstation disk failure or complete replacement
1. Disconnect/isolate hardware and record item/command state if accessible.
2. Replace or repair storage and install a supported operating system/runtime according to the setup runbook.
3. Restore source revision, lockfiles, model artifacts, configuration, database, manifests, and approved data from a verified off-device backup.
4. Verify hashes and database/artifact consistency.
5. Recreate secrets securely or rotate credentials; do not restore secrets from an untrusted export.
6. Confirm local service binding, camera connection, firmware identity, and storage permissions.
7. Run software-only smoke tests and live-camera tests with actuators disabled.
8. Manually reconcile the physical conveyor/item state; never resume a motor from restored software state alone.
9. Record actual recovery time and any unavailable evidence.

### DR-05 — Backup archive corrupted or not restorable
1. Mark the backup as failed/unusable; do not erase it before preserving evidence.
2. Attempt restoration from another verified recovery point.
3. Review the backup job logs, destination capacity, media health, and hash report.
4. If all backups fail, preserve remaining source/data and reconstruct only from verifiable inputs.
5. Mark reconstructed records/artifacts clearly as reconstructed, with provenance and uncertainty.
6. Run a new backup and a separate restore drill before considering recovery complete.

### DR-06 — Lost/stolen workstation or removable backup
1. Revoke/rotate credentials and tokens that may have been stored on the device.
2. Assess exposure of images, labels, configuration, and exported data.
3. Rebuild from a verified, access-controlled backup on a clean device.
4. Revalidate artifact hashes, release manifests, access restrictions, and local-only network binding.
5. Do not restore compromised secrets without rotation.
6. Document the incident and data-disclosure assessment required by the project’s policy.

## 11. Business continuity modes

| Mode | Permitted activity | Required guardrails |
|---|---|---|
| Mode 0 — Safe shutdown | No automatic inspections or actuation | Hardware is de-energized or otherwise held safely; state recorded where possible |
| Mode 1 — Documentation/recovery | Repair files, restore backups, inspect logs | No automatic machine movement; preserve incident evidence |
| Mode 2 — Software-only inspection | Offline dataset/model tests | No conveyor control; clear UI label indicating simulated/software-only mode |
| Mode 3 — Live camera, hardware disabled | Capture and decide from real frames | Verify camera and model; actuator output disabled |
| Mode 4 — Supervised tabletop operation | Controlled end-to-end inspection cycle | All readiness gates pass; physical state known; operator explicitly arms system |

Do not allow a restart or restore to automatically elevate the system from a lower mode to supervised hardware operation.

## 12. Recovery acceptance checklist

- [ ] Recovery point has an ID, timestamp, source revision, model/policy versions, and schema version.
- [ ] Backup has a scope statement and verified hashes.
- [ ] Database backup method is consistent with its engine and journal/WAL behavior.
- [ ] Dataset, label, split, evaluation, and model-release manifests are preserved.
- [ ] Required images/heatmaps exist and match referenced hashes.
- [ ] Secrets are excluded from ordinary backup bundles and can be recreated/rotated safely.
- [ ] Restore can be performed without cloud access.
- [ ] Functional restore includes model-load, policy-load, readiness, and database tests.
- [ ] Camera and ESP32 identities are verified separately after restore.
- [ ] Hardware remains disabled until the physical item/command state is reconciled.
- [ ] No in-flight command is blindly replayed.
- [ ] Recovery time and any data gap are recorded.
- [ ] A new backup is created after successful recovery and independently verified.

## 13. Implementation roadmap

### Phase A — Inventory and recoverability map
- Identify source, configuration, DB, artifacts, model, dataset, firmware, logs, and secret locations.
- Mark each item as reproducible, replaceable, or irreplaceable.
- Define owners and draft RPO/RTO decisions.

### Phase B — Consistent backup implementation
- Use documented database backup method.
- Package manifests, active model/policy versions, required artifacts, and source revision.
- Generate inventory and hashes.
- Write to a separate physical/off-device location.

### Phase C — Restore automation and drills
- Create restore-to-temporary-location procedure.
- Validate database, artifact references, model loading, and application readiness.
- Record elapsed time and failure cases.
- Add recovery checklist to the runbook.

### Phase D — Incident continuity
- Test deletion, corruption, missing model, lost disk, invalid backup, and lost credentials.
- Confirm safe modes and no automatic physical restart.
- Track recovery gaps and corrective work.

### Phase E — Maintainability
- Revisit backup cadence and retention as data volume changes.
- Test after schema/storage changes and before important demonstrations/releases.
- Keep recovery instructions synchronized with actual implementation.

## 14. Open decisions

Resolve after inspecting the actual repository and storage design:
- Database engine, journal/WAL settings, and backup method.
- Exact application/data/model/dataset/artifact paths.
- Which images and heatmaps are mandatory for audit.
- Backup destination, encryption requirement, and who holds removable media.
- RPO, RTO, retention, and backup cadence.
- Whether model memory bank and caches are reconstructible or required for exact release reproduction.
- Secret-management and credential-rotation procedure.
- How to reconstruct or reconcile items processed after the last backup.
- Restore owner and person authorized to resume hardware operation.

## 15. Final rule

Restore data and software only into a verifiable compatible state. A functioning UI or a server that starts is not enough. Until the active model/policy, durable history, referenced artifacts, and physical machine state are verified, the platform must remain in recovery or supervised hold mode.
