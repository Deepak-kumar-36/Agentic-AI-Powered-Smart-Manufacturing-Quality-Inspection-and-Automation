"""Tests for automated SQLite backup, verification, and clean-location restoration (DR-001)."""

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from app.backup import (
    BackupError,
    create_backup,
    main as backup_main,
    restore_backup,
    verify_backup,
)
from app.persistence import InspectionStore
from app.structured_logging import capture_logs


class BackupAndDisasterRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.temp_dir.name)
        self.source_db_path = self.base_dir / "live_inspection.sqlite3"
        self.evidence_dir = self.base_dir / "evidence_storage"
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self.backup_root = self.base_dir / "backups"
        self.backup_root.mkdir(parents=True, exist_ok=True)

        # Create a sample evidence file
        self.sample_img = self.evidence_dir / "item_001.png"
        self.sample_img.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + b"sample-bytes")

        # Initialize and populate store with representative data
        self.store = InspectionStore(self.source_db_path)
        rec1 = self.store.create("idemp-001", {"category": "bottle", "image_path": "item_001.png"})
        self.store.record_decision(
            rec1.inspection_id,
            outcome="PASS",
            reason_codes=["ACCEPTED_BY_POLICY"],
            policy_version="bottle-v1",
            model_version="eff-v1",
            score=0.12,
            evidence={"image_path": "item_001.png", "input_image_sha256": "fake-hash"},
        )
        self.store.add_review(rec1.inspection_id, outcome="CONFIRMED_NORMAL", note="Inspected on line 1")

        rec2 = self.store.create("idemp-002", {"category": "screw"})
        self.store.record_decision(
            rec2.inspection_id,
            outcome="FAIL",
            reason_codes=["REJECTED_BY_POLICY"],
            policy_version="screw-v1",
            model_version="eff-v1",
            score=0.88,
            evidence={"defect": "crack"},
        )
        self.store.add_review(rec2.inspection_id, outcome="CONFIRMED_DEFECT", defect_type="crack")

    def tearDown(self) -> None:
        self.store.close()
        self.temp_dir.cleanup()

    def test_backup_creation_and_manifest_structure(self) -> None:
        with capture_logs() as logs:
            backup_dir, manifest = create_backup(
                self.store,
                self.backup_root,
                evidence_roots=[self.evidence_dir],
                metadata={"reason": "pre-deployment-snapshot"},
            )

        self.assertTrue(backup_dir.is_dir())
        self.assertTrue((backup_dir / "backup_manifest.json").is_file())
        self.assertTrue((backup_dir / manifest.database_filename).is_file())

        self.assertEqual(manifest.record_counts["inspections"], 2)
        self.assertEqual(manifest.record_counts["inspection_reviews"], 2)
        self.assertGreaterEqual(manifest.record_counts["inspection_events"], 4)

        # Evidence file was bundled and hashed
        self.assertIn("item_001.png", manifest.evidence_manifest)
        self.assertTrue((backup_dir / "evidence" / "item_001.png").is_file())

        # Check structured log emission
        backup_events = [e for e in logs if e["event"] == "backup.created"]
        self.assertEqual(len(backup_events), 1)
        self.assertEqual(backup_events[0]["backup_id"], manifest.backup_id)

    def test_verify_valid_backup(self) -> None:
        backup_dir, manifest = create_backup(
            self.store,
            self.backup_root,
            evidence_roots=[self.evidence_dir],
        )

        with capture_logs() as logs:
            result = verify_backup(backup_dir)

        self.assertTrue(result.valid)
        self.assertTrue(result.integrity_ok)
        self.assertTrue(result.foreign_keys_ok)
        self.assertTrue(result.checksums_ok)
        self.assertTrue(result.record_counts_match)
        self.assertTrue(result.evidence_ok)
        self.assertEqual(result.errors, [])

        verify_logs = [e for e in logs if e["event"] == "backup.verified"]
        self.assertEqual(len(verify_logs), 1)
        self.assertEqual(verify_logs[0]["status"], "valid")

    def test_verify_detects_database_tampering(self) -> None:
        backup_dir, manifest = create_backup(
            self.store,
            self.backup_root,
            evidence_roots=[self.evidence_dir],
        )
        db_file = backup_dir / manifest.database_filename

        # Corrupt DB file by appending bytes
        with db_file.open("ab") as stream:
            stream.write(b"corruption-bytes")

        result = verify_backup(backup_dir)
        self.assertFalse(result.valid)
        self.assertFalse(result.checksums_ok)
        self.assertTrue(any("sha256 mismatch" in err for err in result.errors))

    def test_verify_detects_missing_evidence(self) -> None:
        backup_dir, manifest = create_backup(
            self.store,
            self.backup_root,
            evidence_roots=[self.evidence_dir],
        )
        ev_file = backup_dir / "evidence" / "item_001.png"
        ev_file.unlink()

        result = verify_backup(backup_dir)
        self.assertFalse(result.valid)
        self.assertFalse(result.evidence_ok)
        self.assertTrue(any("evidence file missing" in err for err in result.errors))

    def test_clean_location_restore_and_functional_readback(self) -> None:
        backup_dir, manifest = create_backup(
            self.store,
            self.backup_root,
            evidence_roots=[self.evidence_dir],
        )

        # Restore into completely isolated target directory
        isolated_dir = self.base_dir / "restored_environment"
        restored_db = isolated_dir / "restored.sqlite3"
        restored_evidence = isolated_dir / "restored_evidence"

        with capture_logs() as logs:
            res = restore_backup(
                backup_dir,
                restored_db,
                target_evidence_root=restored_evidence,
            )

        self.assertTrue(res.success)
        self.assertEqual(res.restored_evidence_count, 1)
        self.assertTrue((restored_evidence / "item_001.png").is_file())

        # Verify restored DB opens cleanly and functional queries match
        restored_store = InspectionStore(restored_db)
        try:
            records = restored_store.list(50)
            self.assertEqual(len(records), 2)
            by_idemp = {r.idempotency_key: r for r in records}
            self.assertEqual(by_idemp["idemp-001"].outcome, "PASS")
            self.assertEqual(by_idemp["idemp-001"].score, 0.12)
            self.assertEqual(by_idemp["idemp-002"].outcome, "FAIL")

            # Check review records read back
            reviews_1 = restored_store.reviews(by_idemp["idemp-001"].inspection_id)
            self.assertEqual(len(reviews_1), 1)
            self.assertEqual(reviews_1[0].outcome, "CONFIRMED_NORMAL")

            # Check immutable events read back
            events_1 = restored_store.events(by_idemp["idemp-001"].inspection_id)
            event_types = [e["event_type"] for e in events_1]
            self.assertIn("inspection.created", event_types)
            self.assertIn("inspection.decision_recorded", event_types)
            self.assertIn("inspection.review_recorded", event_types)

            # Check review analytics
            analytics = restored_store.review_analytics()
            self.assertEqual(analytics.total_inspections, 2)
            self.assertEqual(analytics.reviewed_inspections, 2)
        finally:
            restored_store.close()

        # Check structured log
        restore_logs = [e for e in logs if e["event"] == "backup.restore.completed"]
        self.assertEqual(len(restore_logs), 1)

    def test_restore_refuses_overwrite_by_default(self) -> None:
        backup_dir, _ = create_backup(self.store, self.backup_root)
        target_path = self.base_dir / "already_exists.sqlite3"
        target_path.touch()

        with self.assertRaises(BackupError) as ctx:
            restore_backup(backup_dir, target_path, overwrite=False)
        self.assertIn("already exists", str(ctx.exception))

        # With overwrite=True, it succeeds
        res = restore_backup(backup_dir, target_path, overwrite=True)
        self.assertTrue(res.success)

    def test_wal_mode_database_consistency(self) -> None:
        wal_db_path = self.base_dir / "wal_db.sqlite3"
        conn = sqlite3.connect(wal_db_path)
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("CREATE TABLE records (id INTEGER PRIMARY KEY, note TEXT)")
        conn.execute("INSERT INTO records (note) VALUES ('uncheckpointed wal row')")
        conn.commit()

        # Notice: we don't checkpoint; the WAL file has uncheckpointed data
        self.assertTrue(Path(str(wal_db_path) + "-wal").exists() or wal_db_path.exists())

        backup_dir, manifest = create_backup(conn, self.backup_root)
        conn.close()

        # Verify backup is valid
        ver = verify_backup(backup_dir)
        self.assertTrue(ver.valid)

        # Restore into clean location and read back
        clean_target = self.base_dir / "wal_restored.sqlite3"
        restore_backup(backup_dir, clean_target)
        check_conn = sqlite3.connect(clean_target)
        row = check_conn.execute("SELECT note FROM records WHERE id = 1").fetchone()
        self.assertEqual(row[0], "uncheckpointed wal row")
        check_conn.close()

    def test_cli_create_verify_restore(self) -> None:
        # CLI create
        cli_backup_dir = self.base_dir / "cli_backups"
        code = backup_main([
            "create",
            "--db", str(self.source_db_path),
            "--backup-root", str(cli_backup_dir),
            "--evidence-root", str(self.evidence_dir),
            "--note", "automated-cli-test",
        ])
        self.assertEqual(code, 0)

        # Locate created directory
        subdirs = [d for d in cli_backup_dir.iterdir() if d.is_dir()]
        self.assertEqual(len(subdirs), 1)
        created_backup = subdirs[0]

        # CLI verify
        verify_code = backup_main(["verify", "--backup-dir", str(created_backup)])
        self.assertEqual(verify_code, 0)

        # CLI restore
        cli_target_db = self.base_dir / "cli_target.sqlite3"
        cli_target_ev = self.base_dir / "cli_target_evidence"
        restore_code = backup_main([
            "restore",
            "--backup-dir", str(created_backup),
            "--target-db", str(cli_target_db),
            "--target-evidence-root", str(cli_target_ev),
        ])
        self.assertEqual(restore_code, 0)
        self.assertTrue(cli_target_db.is_file())
        self.assertTrue((cli_target_ev / "item_001.png").is_file())
