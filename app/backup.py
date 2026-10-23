"""Automated SQLite backup, integrity verification, and clean-location restore.

Follows Document 16 (Backup & Disaster Recovery) and PRD DR-001:
- Consistent SQLite online backup via sqlite3.Connection.backup (WAL and rollback journal safe).
- Bounded preservation of inspection records, review history, and immutable events.
- Checksums (SHA-256) of database snapshot and referenced evidence assets.
- PRAGMA integrity_check and PRAGMA foreign_key_check validation.
- Clean-location restoration into isolated directories without live database overwriting.
- Structured event logging (backup.created, backup.verified, backup.restore.completed).
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
from typing import Any, Mapping, Sequence
from uuid import uuid4

from .persistence import InspectionStore
from .structured_logging import logger

BACKUP_SCHEMA_VERSION = "1.0"
APP_VERSION = "0.1.0"


class BackupError(Exception):
    """Raised when backup creation, verification, or restoration fails."""


@dataclass(frozen=True)
class BackupManifest:
    backup_id: str
    created_at: str
    schema_version: str
    app_version: str
    database_filename: str
    database_sha256: str
    database_size_bytes: int
    record_counts: dict[str, int]
    evidence_manifest: dict[str, dict[str, Any]]
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BackupManifest:
        return cls(
            backup_id=data["backup_id"],
            created_at=data["created_at"],
            schema_version=data["schema_version"],
            app_version=data.get("app_version", APP_VERSION),
            database_filename=data["database_filename"],
            database_sha256=data["database_sha256"],
            database_size_bytes=data["database_size_bytes"],
            record_counts=dict(data.get("record_counts", {})),
            evidence_manifest=dict(data.get("evidence_manifest", {})),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass(frozen=True)
class BackupVerificationResult:
    valid: bool
    backup_id: str
    integrity_ok: bool
    foreign_keys_ok: bool
    checksums_ok: bool
    record_counts_match: bool
    evidence_ok: bool
    errors: list[str]


@dataclass(frozen=True)
class RestoreResult:
    success: bool
    backup_id: str
    restored_database: str
    restored_evidence_count: int
    restored_record_counts: dict[str, int]


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def _get_connection(source: str | Path | sqlite3.Connection | InspectionStore) -> tuple[sqlite3.Connection, bool]:
    """Return a connection and whether it needs to be closed by caller."""
    if isinstance(source, InspectionStore):
        return source.connection, False
    if isinstance(source, sqlite3.Connection):
        return source, False
    path = Path(source)
    if not path.is_file():
        raise BackupError(f"source database file does not exist: {path}")
    conn = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn, True


def create_backup(
    source: str | Path | sqlite3.Connection | InspectionStore,
    backup_root: str | Path,
    *,
    evidence_roots: Sequence[str | Path] = (),
    metadata: Mapping[str, Any] | None = None,
    backup_id: str | None = None,
) -> tuple[Path, BackupManifest]:
    """Create a consistent SQLite backup and manifest."""
    source_conn, should_close = _get_connection(source)
    try:
        now_dt = datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()
        b_id = backup_id or f"bkp_{now_dt.strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}"

        backup_dir = Path(backup_root).resolve() / b_id
        backup_dir.mkdir(parents=True, exist_ok=True)
        evidence_dir = backup_dir / "evidence"

        # Pre-check database integrity on source connection
        try:
            integrity = source_conn.execute("PRAGMA integrity_check").fetchall()
            if not integrity or integrity[0][0] != "ok":
                errors = [row[0] for row in integrity]
                raise BackupError(f"source database failed integrity check: {errors}")
        except sqlite3.Error as exc:
            raise BackupError(f"could not verify source database integrity: {exc}") from exc

        # Copy database consistently via native SQLite backup API
        db_filename = "inspection_backup.sqlite3"
        dest_db_path = backup_dir / db_filename
        dest_conn = sqlite3.connect(dest_db_path)
        try:
            with dest_conn:
                source_conn.backup(dest_conn, pages=100)
        finally:
            dest_conn.close()

        # Compute checksum of created backup DB
        db_sha256 = _sha256_file(dest_db_path)
        db_size = dest_db_path.stat().st_size

        # Query counts and gather referenced evidence files from backup
        counts: dict[str, int] = {}
        evidence_manifest: dict[str, dict[str, Any]] = {}
        resolved_evidence_roots = [Path(r).resolve() for r in evidence_roots]

        verify_conn = sqlite3.connect(f"file:{dest_db_path.resolve()}?mode=ro", uri=True)
        verify_conn.row_factory = sqlite3.Row
        try:
            existing_tables = {
                r[0] for r in verify_conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
            }
            for table in existing_tables:
                row = verify_conn.execute(f"SELECT COUNT(*) AS c FROM [{table}]").fetchone()
                counts[table] = int(row["c"]) if row else 0

            # Find referenced images in inspections if table exists
            if "inspections" in existing_tables:
                rows = verify_conn.execute("SELECT inspection_id, evidence_json FROM inspections").fetchall()
                for r in rows:
                    try:
                        ev = json.loads(r["evidence_json"] or "{}")
                    except (ValueError, TypeError):
                        continue
                    img_path_str = ev.get("image_path")
                    if isinstance(img_path_str, str) and img_path_str.strip():
                        img_name = Path(img_path_str).name
                        expected_hash = ev.get("input_image_sha256")
                        
                        # Search evidence roots for this file
                        src_file: Path | None = None
                        for root in resolved_evidence_roots:
                            candidate = root / img_name
                            if candidate.is_file():
                                src_file = candidate
                                break

                        if src_file is not None and src_file.is_file():
                            evidence_dir.mkdir(parents=True, exist_ok=True)
                            dest_file = evidence_dir / img_name
                            if not dest_file.exists():
                                shutil.copy2(src_file, dest_file)
                            f_hash = _sha256_file(dest_file)
                            evidence_manifest[img_name] = {
                                "sha256": f_hash,
                                "size_bytes": dest_file.stat().st_size,
                                "hash_matched": (f_hash == expected_hash) if expected_hash else True,
                            }

        finally:
            verify_conn.close()

        manifest = BackupManifest(
            backup_id=b_id,
            created_at=now_iso,
            schema_version=BACKUP_SCHEMA_VERSION,
            app_version=APP_VERSION,
            database_filename=db_filename,
            database_sha256=db_sha256,
            database_size_bytes=db_size,
            record_counts=counts,
            evidence_manifest=evidence_manifest,
            metadata=dict(metadata or {}),
        )

        manifest_path = backup_dir / "backup_manifest.json"
        manifest_path.write_text(json.dumps(manifest.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")

        logger.info(
            "backup.created",
            backup_id=b_id,
            database_bytes=db_size,
            inspections_count=counts.get("inspections", 0),
            reviews_count=counts.get("inspection_reviews", 0),
            events_count=counts.get("inspection_events", 0),
            evidence_count=len(evidence_manifest),
        )
        return backup_dir, manifest

    except Exception as exc:
        logger.error("backup.failed", error=str(exc))
        raise
    finally:
        if should_close:
            source_conn.close()


def verify_backup(backup_dir: str | Path) -> BackupVerificationResult:
    """Verify level 1 (checksums) and level 2 (data consistency) of a backup."""
    b_dir = Path(backup_dir).resolve()
    manifest_path = b_dir / "backup_manifest.json"
    if not manifest_path.is_file():
        return BackupVerificationResult(
            valid=False, backup_id="unknown", integrity_ok=False, foreign_keys_ok=False,
            checksums_ok=False, record_counts_match=False, evidence_ok=False,
            errors=[f"manifest not found: {manifest_path}"],
        )

    try:
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest = BackupManifest.from_dict(manifest_data)
    except Exception as exc:
        return BackupVerificationResult(
            valid=False, backup_id="unknown", integrity_ok=False, foreign_keys_ok=False,
            checksums_ok=False, record_counts_match=False, evidence_ok=False,
            errors=[f"failed to parse manifest: {exc}"],
        )

    errors: list[str] = []
    checksums_ok = True
    integrity_ok = True
    foreign_keys_ok = True
    record_counts_match = True
    evidence_ok = True

    # 1. Verify DB file checksum
    db_path = b_dir / manifest.database_filename
    if not db_path.is_file():
        checksums_ok = False
        errors.append(f"database file missing: {db_path}")
    else:
        calc_hash = _sha256_file(db_path)
        if calc_hash != manifest.database_sha256:
            checksums_ok = False
            errors.append(f"database sha256 mismatch: expected {manifest.database_sha256}, got {calc_hash}")

    # 2. Verify evidence file checksums
    evidence_dir = b_dir / "evidence"
    for filename, info in manifest.evidence_manifest.items():
        ev_file = evidence_dir / filename
        if not ev_file.is_file():
            evidence_ok = False
            errors.append(f"evidence file missing: {filename}")
            continue
        ev_hash = _sha256_file(ev_file)
        if ev_hash != info["sha256"]:
            evidence_ok = False
            errors.append(f"evidence sha256 mismatch for {filename}: expected {info['sha256']}, got {ev_hash}")

    # 3. Check SQLite database integrity and record counts
    if checksums_ok and db_path.is_file():
        conn = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            # PRAGMA integrity_check
            integ = conn.execute("PRAGMA integrity_check").fetchall()
            if not integ or integ[0][0] != "ok":
                integrity_ok = False
                errors.append(f"integrity check failed: {[r[0] for r in integ]}")

            # PRAGMA foreign_key_check
            fks = conn.execute("PRAGMA foreign_key_check").fetchall()
            if fks:
                foreign_keys_ok = False
                errors.append(f"foreign key violations found: {len(fks)}")

            # Check counts
            for table, expected in manifest.record_counts.items():
                row = conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()
                observed = int(row["c"]) if row else 0
                if observed != expected:
                    record_counts_match = False
                    errors.append(f"record count mismatch in {table}: expected {expected}, observed {observed}")
        except sqlite3.Error as exc:
            integrity_ok = False
            errors.append(f"sqlite verification error: {exc}")
        finally:
            conn.close()
    else:
        integrity_ok = False
        foreign_keys_ok = False
        record_counts_match = False

    valid = checksums_ok and integrity_ok and foreign_keys_ok and record_counts_match and evidence_ok
    if valid:
        logger.info("backup.verified", backup_id=manifest.backup_id, status="valid")
    else:
        logger.warning("backup.verified", backup_id=manifest.backup_id, status="invalid", errors=errors)

    return BackupVerificationResult(
        valid=valid,
        backup_id=manifest.backup_id,
        integrity_ok=integrity_ok,
        foreign_keys_ok=foreign_keys_ok,
        checksums_ok=checksums_ok,
        record_counts_match=record_counts_match,
        evidence_ok=evidence_ok,
        errors=errors,
    )


def restore_backup(
    backup_dir: str | Path,
    target_db_path: str | Path,
    *,
    target_evidence_root: str | Path | None = None,
    overwrite: bool = False,
    verify_first: bool = True,
) -> RestoreResult:
    """Restore a verified backup to a target database path and optional evidence root."""
    target_db = Path(target_db_path).resolve()
    if target_db.exists() and not overwrite:
        raise BackupError(f"target database already exists: {target_db} (use overwrite=True to allow)")

    if verify_first:
        verification = verify_backup(backup_dir)
        if not verification.valid:
            raise BackupError(f"cannot restore invalid backup {verification.backup_id}: {verification.errors}")

    b_dir = Path(backup_dir).resolve()
    manifest_data = json.loads((b_dir / "backup_manifest.json").read_text(encoding="utf-8"))
    manifest = BackupManifest.from_dict(manifest_data)

    src_db = b_dir / manifest.database_filename
    target_db.parent.mkdir(parents=True, exist_ok=True)

    # Atomically copy database file
    temp_target = target_db.parent / f".tmp_{target_db.name}_{uuid4().hex[:8]}"
    try:
        shutil.copy2(src_db, temp_target)
        os.replace(temp_target, target_db)
    except Exception as exc:
        if temp_target.exists():
            temp_target.unlink()
        logger.error("restore.failed", backup_id=manifest.backup_id, error=str(exc))
        raise BackupError(f"failed to restore database file: {exc}") from exc

    # Restore evidence assets if target directory is provided
    restored_evidence_count = 0
    if target_evidence_root is not None:
        ev_target_dir = Path(target_evidence_root).resolve()
        ev_target_dir.mkdir(parents=True, exist_ok=True)
        ev_src_dir = b_dir / "evidence"
        if ev_src_dir.is_dir():
            for filename in manifest.evidence_manifest.keys():
                src_item = ev_src_dir / filename
                if src_item.is_file():
                    shutil.copy2(src_item, ev_target_dir / filename)
                    restored_evidence_count += 1

    # Verify restored database opens and functions
    conn = sqlite3.connect(target_db)
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()}
        counts: dict[str, int] = {}
        for t in tables:
            row = conn.execute(f"SELECT COUNT(*) AS c FROM [{t}]").fetchone()
            counts[t] = int(row[0]) if row else 0
    finally:
        conn.close()

    if "inspections" in tables:
        store = InspectionStore(target_db)
        try:
            store.list(limit=50)
        finally:
            store.close()


    logger.info(
        "backup.restore.completed",
        backup_id=manifest.backup_id,
        target_db=str(target_db),
        restored_evidence=restored_evidence_count,
    )

    return RestoreResult(
        success=True,
        backup_id=manifest.backup_id,
        restored_database=str(target_db),
        restored_evidence_count=restored_evidence_count,
        restored_record_counts=counts,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspection platform SQLite backup and restore CLI")
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # create
    create_p = subparsers.add_parser("create", help="Create a consistent backup snapshot")
    create_p.add_argument("--db", type=Path, required=True, help="path to source SQLite database")
    create_p.add_argument("--backup-root", type=Path, required=True, help="root directory where backup will be saved")
    create_p.add_argument("--evidence-root", action="append", type=Path, default=[], help="directory to resolve referenced evidence images")
    create_p.add_argument("--note", type=str, default=None, help="optional description or incident note")

    # verify
    verify_p = subparsers.add_parser("verify", help="Verify checksums, integrity, and references in a backup")
    verify_p.add_argument("--backup-dir", type=Path, required=True, help="path to specific backup directory")

    # restore
    restore_p = subparsers.add_parser("restore", help="Restore a backup into a clean target location")
    restore_p.add_argument("--backup-dir", type=Path, required=True, help="path to specific backup directory")
    restore_p.add_argument("--target-db", type=Path, required=True, help="path for restored SQLite database")
    restore_p.add_argument("--target-evidence-root", type=Path, default=None, help="directory to restore evidence images")
    restore_p.add_argument("--overwrite", action="store_true", help="allow overwriting target database if it exists")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.subcommand == "create":
        try:
            metadata = {"note": args.note} if args.note else {}
            b_dir, manifest = create_backup(
                args.db,
                args.backup_root,
                evidence_roots=args.evidence_root,
                metadata=metadata,
            )
            print(f"Backup created successfully: {b_dir} (ID: {manifest.backup_id})")
            return 0
        except BackupError as exc:
            print(f"Backup creation error: {exc}", file=sys.stderr)
            return 1

    if args.subcommand == "verify":
        res = verify_backup(args.backup_dir)
        if res.valid:
            print(f"Backup {res.backup_id} is VALID and fully consistent.")
            return 0
        else:
            print(f"Backup {res.backup_id} is INVALID! Errors:", file=sys.stderr)
            for err in res.errors:
                print(f"  - {err}", file=sys.stderr)
            return 1

    if args.subcommand == "restore":
        try:
            res = restore_backup(
                args.backup_dir,
                args.target_db,
                target_evidence_root=args.target_evidence_root,
                overwrite=args.overwrite,
            )
            print(f"Restored backup {res.backup_id} to {res.restored_database} ({res.restored_evidence_count} evidence files).")
            return 0
        except BackupError as exc:
            print(f"Restore error: {exc}", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
